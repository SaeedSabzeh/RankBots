"""Duels against a real Postgres: checks, the atomic accept, expiry, direction."""

import asyncio
import random
from datetime import datetime, timedelta, timezone

import pytest

from engine import game, service, texts
from engine.db import Blocked
from engine.theme import load_themes

# These tests use round scores like 50 g, so they run on a cat with a floor of 0.
_CAT = load_themes()["cat"]
CAT = _CAT.model_copy(update={
    "score": _CAT.score.model_copy(update={"start": 0, "min": 0}),
    "titles": [t.model_copy(update={"at": t.at - _CAT.score.start}) for t in _CAT.titles],
})
CAT_BOTH = CAT.model_copy(update={"language": "both"})
KONKUR = CAT.model_copy(
    update={
        "name": "konkur",
        "score": CAT.score.model_copy(update={"start": 500_000, "direction": "lower", "scale": 1000, "min": 1}),
        "titles": [CAT.titles[0].model_copy(update={"at": 500_000})],
    }
)
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
CHAT = -100123


class Pick(random.Random):
    """choice() always takes the item at `index`: 0 is the challenger, 1 the target."""

    def __init__(self, index):
        super().__init__(0)
        self.index = index

    def choice(self, seq):
        return seq[self.index]


async def _seed(store, user_id, score, theme=CAT, played=True):
    await store.touch_chat(theme.name, CHAT, "Test group", 12)
    await store.ensure_player(theme.name, CHAT, user_id, f"user{user_id}", f"User {user_id}", theme.score.start)
    await store.pool.execute(
        "UPDATE players SET score = $1, last_play_at = $2 WHERE bot = $3 AND chat_id = $4 AND user_id = $5",
        score, T0 if played else None, theme.name, CHAT, user_id,
    )


def _who(user_id, is_bot=False):
    return service.Who(user_id, f"user{user_id}", f"User {user_id}", is_bot)


async def _challenge(store, challenger=1, target=2, stake=10, now=T0, theme=CAT):
    if isinstance(target, int):
        target = _who(target)
    return await service.challenge(
        store, theme, chat_id=CHAT, chat_title="Test group",
        challenger=_who(challenger), target=target, stake=stake, now=now,
    )


async def _answer(store, duel_id, user_id=2, accept=True, now=T0, theme=CAT, winner=0):
    return await service.answer_duel(
        store, theme, duel_id=duel_id, user_id=user_id, accept=accept, now=now, rng=Pick(winner)
    )


async def _score(store, user_id, theme=CAT):
    return (await store.get_player(theme.name, CHAT, user_id)).score


async def test_accepted_duel_moves_the_stake_and_not_the_play_cooldown(store):
    await _seed(store, 1, 50)
    await _seed(store, 2, 30)
    offer = await _challenge(store, stake=20)
    assert isinstance(offer, service.DuelOffer)
    assert offer.challenger.user_id == 1 and offer.target.user_id == 2

    r = await _answer(store, offer.duel_id, now=T0 + timedelta(minutes=3), winner=1)
    assert isinstance(r, service.DuelResult)
    assert (r.winner.user_id, r.loser.user_id, r.winner_delta) == (2, 1, 20)
    assert await _score(store, 1) == 30 and await _score(store, 2) == 50

    duel = await store.get_duel("cat", offer.duel_id)
    assert duel.status == "accepted" and duel.winner_id == 2
    log = await store.pool.fetch("SELECT user_id, delta, event, score_after FROM plays ORDER BY user_id")
    assert [tuple(row) for row in log] == [(1, -20, "duel", 30), (2, 20, "duel", 50)]

    # Both players used their duel; neither used their /play turn.
    for user_id in (1, 2):
        p = await store.get_player("cat", CHAT, user_id)
        assert p.last_duel_at == T0 + timedelta(minutes=3) and p.last_play_at == T0

    out = texts.duel_result(CAT_BOTH, r)
    assert "User 2" in out and "beat" in out and "برد" in out


async def test_only_the_target_can_answer(store):
    await _seed(store, 1, 50)
    await _seed(store, 2, 50)
    await _seed(store, 3, 50)
    offer = await _challenge(store)
    assert await _answer(store, offer.duel_id, user_id=1) == service.NotYourDuel()
    assert await _answer(store, offer.duel_id, user_id=3, accept=False) == service.NotYourDuel()
    assert (await store.get_duel("cat", offer.duel_id)).status == "pending"


async def test_decline_then_late_taps(store):
    await _seed(store, 1, 50)
    await _seed(store, 2, 50)
    offer = await _challenge(store)
    r = await _answer(store, offer.duel_id, accept=False)
    assert isinstance(r, service.DuelClosed) and r.status == "declined"
    assert "declined" in texts.duel_closed(CAT_BOTH, r)
    assert await _answer(store, offer.duel_id) == service.DuelGone()
    assert await _score(store, 1) == 50
    # A declined duel doesn't count toward the 6-hour limit.
    assert isinstance(await _challenge(store, now=T0 + timedelta(minutes=1)), service.DuelOffer)


async def test_duel_expires_after_ten_minutes(store):
    await _seed(store, 1, 50)
    await _seed(store, 2, 50)
    offer = await _challenge(store)
    r = await _answer(store, offer.duel_id, now=T0 + game.DUEL_EXPIRY)
    assert isinstance(r, service.DuelClosed) and r.status == "expired"
    assert (await store.get_duel("cat", offer.duel_id)).status == "expired"
    assert await _score(store, 2) == 50
    # The challenger can open a new one.
    assert isinstance(await _challenge(store, now=T0 + game.DUEL_EXPIRY), service.DuelOffer)


async def test_double_tap_on_accept_settles_once(store):
    await _seed(store, 1, 50)
    await _seed(store, 2, 50)
    offer = await _challenge(store, stake=10)
    results = await asyncio.gather(*(_answer(store, offer.duel_id) for _ in range(8)))
    assert sum(isinstance(r, service.DuelResult) for r in results) == 1
    assert all(isinstance(r, (service.DuelResult, service.DuelGone)) for r in results)
    assert await _score(store, 1) + await _score(store, 2) == 100
    assert await store.pool.fetchval("SELECT count(*) FROM plays") == 2


async def test_one_duel_per_user_every_six_hours(store):
    for user_id in (1, 2, 3):
        await _seed(store, user_id, 50)
    offer = await _challenge(store)
    await _answer(store, offer.duel_id)

    # Both players are now on the duel cooldown, as challenger or as target.
    r = await _challenge(store, challenger=1, target=3, now=T0 + timedelta(hours=2))
    assert r.reason == "cooldown" and r.left == timedelta(hours=4) and r.first_name == "User 1"
    r = await _challenge(store, challenger=3, target=2, now=T0 + timedelta(hours=2))
    assert r.reason == "cooldown" and r.first_name == "User 2"
    assert "4h" in texts.duel_refused(CAT_BOTH, r)

    assert isinstance(await _challenge(store, challenger=1, target=3, now=T0 + timedelta(hours=6)), service.DuelOffer)


async def test_target_who_accepts_two_duels_only_fights_one(store):
    for user_id in (1, 2, 3):
        await _seed(store, user_id, 50)
    first = await _challenge(store, challenger=1, target=2)
    second = await _challenge(store, challenger=3, target=2)
    assert isinstance(await _answer(store, first.duel_id), service.DuelResult)
    r = await _answer(store, second.duel_id)
    assert isinstance(r, service.DuelRefused) and r.reason == "cooldown"
    assert (await store.get_duel("cat", second.duel_id)).status == "pending"


async def test_both_players_need_the_stake(store):
    await _seed(store, 1, 50)
    await _seed(store, 2, 9)
    r = await _challenge(store, stake=10)
    assert r.reason == "short" and r.first_name == "User 2" and r.max_stake == 9
    r = await _challenge(store, stake=51)
    assert r.reason == "short" and r.first_name == "User 1"
    assert "at most" in texts.duel_refused(CAT_BOTH, r)
    assert isinstance(await _challenge(store, stake=9), service.DuelOffer)


async def test_stake_is_rechecked_when_accepted(store):
    await _seed(store, 1, 50)
    await _seed(store, 2, 50)
    offer = await _challenge(store, stake=40)
    await store.pool.execute("UPDATE players SET score = 30 WHERE user_id = 1")  # a bad /play in between
    r = await _answer(store, offer.duel_id)
    assert r.reason == "short" and r.first_name == "User 1" and r.max_stake == 30
    assert (await store.get_duel("cat", offer.duel_id)).status == "pending"
    assert await store.pool.fetchval("SELECT count(*) FROM players WHERE last_duel_at IS NOT NULL") == 0


async def test_accept_rolls_back_completely_when_blocked(store):
    await _seed(store, 1, 50)
    await _seed(store, 2, 5)
    duel_id = await store.create_duel("cat", CHAT, 1, 2, 10, now=T0, expiry=game.DUEL_EXPIRY)
    out = await store.accept_duel(
        "cat", duel_id, winner_id=1, winner_delta=10, min_score=0,
        now=T0, expiry=game.DUEL_EXPIRY, duel_cooldown_hours=6,
    )
    assert isinstance(out, Blocked) and out.reason == "short" and out.player.user_id == 2
    assert (await store.get_duel("cat", duel_id)).status == "pending"
    assert await _score(store, 1) == 50 and await _score(store, 2) == 5


async def test_who_can_be_challenged(store):
    await _seed(store, 1, 50)
    await _seed(store, 2, 50, played=False)
    assert (await _challenge(store, target=1)).reason == "self"
    assert (await _challenge(store, target=_who(99, is_bot=True))).reason == "bot"
    assert (await _challenge(store, target=2)).reason == "not_played"
    assert (await _challenge(store, target=42)).reason == "not_played"  # never seen in this group
    r = await _challenge(store, target="@nobody")
    assert r.reason == "unknown" and r.username == "nobody"
    assert "@nobody" in texts.duel_refused(CAT, r)


async def test_target_by_username_is_case_insensitive(store):
    await _seed(store, 1, 50)
    await _seed(store, 2, 50)
    offer = await _challenge(store, target="@USER2")
    assert offer.target.user_id == 2
    assert "User 2" in texts.duel_offer(CAT_BOTH, offer) and "۱۰" in texts.duel_offer(CAT_BOTH, offer)


async def test_one_open_challenge_at_a_time(store):
    for user_id in (1, 2, 3):
        await _seed(store, user_id, 50)
    assert isinstance(await _challenge(store, target=2), service.DuelOffer)
    r = await _challenge(store, target=3, now=T0 + timedelta(minutes=5))
    assert r.reason == "pending" and r.first_name == "User 1"


@pytest.mark.parametrize("winner", [0, 1])
async def test_lower_is_better_duel(store, winner):
    # Konkur: rank 1 is the best, so winning lowers your rank by the stake.
    await _seed(store, 1, 10, theme=KONKUR)
    await _seed(store, 2, 400_000, theme=KONKUR)
    # Rank 10 can improve by at most 9, so that is the most it can stake.
    r = await _challenge(store, stake=10, theme=KONKUR)
    assert r.reason == "short" and r.first_name == "User 1" and r.max_stake == 9

    offer = await _challenge(store, stake=9, theme=KONKUR)
    r = await _answer(store, offer.duel_id, theme=KONKUR, winner=winner)
    assert r.winner_delta == -9
    if winner == 0:
        assert (await _score(store, 1, KONKUR), await _score(store, 2, KONKUR)) == (1, 400_009)
    else:
        assert (await _score(store, 1, KONKUR), await _score(store, 2, KONKUR)) == (19, 399_991)
