"""The play flow against a real Postgres: cooldown, races, floor, leaderboard, theme hook."""

import asyncio
import random
from datetime import datetime, timedelta, timezone

from engine import service, texts
from engine.theme import Theme, load_themes

CAT = load_themes()["cat"]
TAAROF = Theme.model_validate({
    **CAT.model_dump(),
    "name": "taarof",
    "hook": {
        "kind": "lost_turn",
        "chance": 0.1,
        "messages": [{"en": "The bot insisted: after you! Your turn went to the bot",
                      "fa": "ربات تعارف کرد: «اول شما!» نوبتت پرید"}],
    },
})
CAT_BOTH = CAT.model_copy(update={"language": "both"})
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
CHAT = -100123


async def _play(store, user_id=1, now=T0, chat_id=CHAT, theme=CAT, seed=None, rng=None):
    return await service.play(
        store, theme,
        chat_id=chat_id, chat_title="Test group",
        user_id=user_id, username=f"user{user_id}", first_name=f"User {user_id}",
        now=now, rng=rng or random.Random(seed if seed is not None else user_id),
    )


class _AlwaysHook(random.Random):
    """random() returns 0, so a theme hook with any chance fires."""

    def random(self):
        return 0.0


async def test_migrations_can_run_twice(store):
    await store.migrate()


async def test_play_then_cooldown_then_play_again(store):
    first = await _play(store)
    assert isinstance(first, service.Played)
    assert first.rank == 1
    assert first.score == max(CAT.score.min, CAT.score.start + first.delta)

    again = await _play(store, now=T0 + timedelta(hours=3))
    assert again == service.OnCooldown(timedelta(hours=9))

    later = await _play(store, now=T0 + timedelta(hours=12))
    assert isinstance(later, service.Played)

    log = await store.pool.fetch("SELECT delta, score_after FROM plays ORDER BY id")
    assert [r["score_after"] for r in log] == [first.score, later.score]


async def test_double_tap_counts_once(store):
    results = await asyncio.gather(*(_play(store, seed=i) for i in range(8)))
    assert sum(isinstance(r, service.Played) for r in results) == 1
    assert await store.pool.fetchval("SELECT count(*) FROM plays") == 1


async def test_streak_grows_on_consecutive_days_and_resets(store):
    day = timedelta(days=1)
    streaks = []
    for now in (T0, T0 + day, T0 + 2 * day, T0 + 4 * day):
        r = await _play(store, now=now)
        streaks.append(r.streak)
    assert streaks == [0, 1, 2, 0]


async def test_score_floor_is_enforced_in_sql(store):
    await _play(store)
    p = await store.get_player("cat", CHAT, 1)
    score = await store.try_play(
        "cat", CHAT, 1,
        now=T0 + timedelta(hours=13), today=T0.date(), cooldown_hours=12,
        seen_last_play_at=p.last_play_at, delta=-10_000, min_score=0, streak=0, event=None,
    )
    assert score == 0


async def test_scores_are_per_group_and_per_bot(store):
    await _play(store, chat_id=1)
    assert isinstance(await _play(store, chat_id=2), service.Played)  # other group: no cooldown
    other_bot = CAT.model_copy(update={"name": "chai"})
    assert isinstance(await _play(store, chat_id=1, theme=other_bot), service.Played)
    assert await store.player_count("cat", 1) == 1
    assert await store.player_count("chai", 1) == 1


async def test_leaderboard_and_my_rank(store):
    for user_id, score in [(1, 50), (2, 120), (3, 10), (4, 120)]:
        await store.touch_chat("cat", CHAT, "g", 12)
        await store.ensure_player("cat", CHAT, user_id, None, f"U{user_id}", 0)
        await store.pool.execute(
            "UPDATE players SET score = $1, last_play_at = $2 WHERE user_id = $3", score, T0, user_id
        )

    b = await service.board(store, CAT, chat_id=CHAT, user_id=3, limit=2)
    assert [p.user_id for p in b.top] == [2, 4] or [p.user_id for p in b.top] == [4, 2]
    assert b.me.user_id == 3 and b.my_rank == 4
    assert await store.rank_of("cat", CHAT, 50, True) == 3  # two tied players at 120 are ahead

    st = await service.stats(store, CAT, chat_id=CHAT, user_id=2, now=T0 + timedelta(hours=1))
    assert st.rank == 1 and st.players == 4
    assert st.cooldown_left == timedelta(hours=11)

    # Every message renders in both languages.
    out = texts.top(CAT_BOTH, b)
    assert "U2" in out and "U3" in out and "🥇" in out
    assert "گرم" in texts.me(CAT_BOTH, "U2", st)


async def test_me_before_playing(store):
    assert await service.stats(store, CAT, chat_id=CHAT, user_id=99, now=T0) is None


async def test_play_messages_render(store):
    r = await _play(store)
    for theme in (CAT, CAT_BOTH):
        out = texts.play_result(theme, "Simin", r)
        assert "Simin" in out and "۱۲ ساعت" in out
    assert "Next try in 12h" in texts.play_result(CAT_BOTH, "Simin", r)


async def test_taarof_lost_turn_uses_the_cooldown_but_not_the_score(store):
    await _play(store, theme=TAAROF, seed=0)
    before = (await store.get_player("taarof", CHAT, 1)).score

    r = await _play(store, theme=TAAROF, now=T0 + timedelta(days=1), rng=_AlwaysHook(1))
    assert isinstance(r, service.Played)
    assert r.roll.event == "lost_turn" and r.delta == 0 and r.score == before
    assert r.streak == 1  # showing up still counts for the streak
    assert await _play(store, theme=TAAROF, now=T0 + timedelta(days=1, hours=1)) == service.OnCooldown(
        timedelta(hours=11)
    )

    log = await store.pool.fetch("SELECT delta, event FROM plays WHERE bot = 'taarof' ORDER BY id")
    assert [(row["delta"], row["event"]) for row in log][-1] == (0, "lost_turn")

    out = texts.play_result(TAAROF.model_copy(update={"language": "both"}), "Simin", r)
    assert "after you" in out and "نوبتت پرید" in out
    assert "+" not in out.split("\n")[1]  # no "+0 g" after the joke
