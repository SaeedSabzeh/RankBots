"""Achievements: who earns what, and that each is announced only once."""

import random
from datetime import datetime, timedelta, timezone

from engine import achievements, game, service, texts
from engine.theme import load_themes

CAT = load_themes()["cat"]
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
CHAT = -100321


def test_rules():
    kw = dict(streak=0, event=None, boosts=(), rank=2, players=2, plays=1)
    assert achievements.after_play(**kw) == []
    assert achievements.after_play(**{**kw, "streak": 7}) == ["streak_3", "streak_7"]
    assert achievements.after_play(**{**kw, "event": "good"}) == ["jackpot"]
    assert achievements.after_play(**{**kw, "event": "lost_turn"}) == ["taarofed"]
    assert achievements.after_play(**{**kw, "boosts": ("lucky_hour", "nowruz")}) == ["lucky_hour", "holiday"]
    assert achievements.after_play(**{**kw, "rank": 1, "players": 2}) == []  # #1 of two doesn't count
    assert achievements.after_play(**{**kw, "rank": 1, "players": 3}) == ["top"]
    assert achievements.after_play(**{**kw, "plays": 200}) == ["plays_50", "plays_200"]
    assert achievements.after_duel_win(5) == ["duel_1", "duel_5"]


def test_every_achievement_has_both_languages():
    for a in achievements.ALL:
        assert a.name["fa"].strip() and a.name["en"].strip() and a.emoji


class Jackpot(random.Random):
    """Always rolls a rare event, and always the good kind."""

    def random(self):
        return 0.0

    def choice(self, seq):
        return seq[0]


async def _play(store, now, rng):
    return await service.play(
        store, CAT, chat_id=CHAT, chat_title="g", user_id=1, username="u", first_name="Simin", now=now, rng=rng,
    )


async def test_badge_is_announced_once_and_shown_in_me(store):
    first = await _play(store, T0, Jackpot(0))
    assert first.roll.event == "good" and "jackpot" in first.new_badges
    assert "اولین جکپات" in texts.play_result(CAT, "Simin", first)

    second = await _play(store, T0 + timedelta(hours=2), Jackpot(0))
    assert "jackpot" not in second.new_badges

    st = await service.stats(store, CAT, chat_id=CHAT, user_id=1, now=T0 + timedelta(hours=2))
    assert "jackpot" in st.badges
    assert "دستاوردها" in texts.me(CAT, "Simin", st) and "✨" in texts.me(CAT, "Simin", st)


async def test_streak_badge(store):
    day = timedelta(days=1)
    rng = random.Random(4)
    results = [await _play(store, T0 + i * day, rng) for i in range(4)]
    assert results[2].streak == 2 and "streak_3" not in results[2].new_badges
    assert results[3].streak == 3 and "streak_3" in results[3].new_badges


async def test_duel_win_badge(store):
    for user_id, score in ((1, 50), (2, 50)):
        await store.touch_chat(CAT.name, CHAT, "g")
        await store.ensure_player(CAT.name, CHAT, user_id, f"u{user_id}", f"U{user_id}", CAT.score.start)
        await store.pool.execute("UPDATE players SET score = $1, last_play_at = $2 WHERE user_id = $3",
                                 score + CAT.score.min, T0, user_id)
    offer = await service.challenge(store, CAT, chat_id=CHAT, chat_title="g", challenger=service.Who(1, "u1", "U1"),
                                    target=service.Who(2, "u2", "U2"), stake=10, now=T0)
    class First(random.Random):
        def choice(self, seq):
            return seq[0]
    result = await service.answer_duel(store, CAT, duel_id=offer.duel_id, user_id=2, accept=True, now=T0, rng=First(0))
    assert result.winner.user_id == 1 and result.winner_badges == ("duel_1",)
    assert "اولین برد دوئل" in texts.duel_result(CAT, result)
