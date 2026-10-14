"""Lucky hours, Persian holidays and the weekly champion post."""

import random
from datetime import date, datetime, timedelta, timezone

import pytest

from engine import champion, game, service, texts
from engine.theme import load_themes

THEMES = load_themes()
CAT = THEMES["cat"].model_copy(update={"cooldown_minutes": 60})
CAT_BOTH = CAT.model_copy(update={"language": "both"})
KONKUR = THEMES["konkur"]
CHAT = -100777


@pytest.mark.parametrize(
    ("day", "jalali"),
    [
        (date(2025, 3, 21), (1404, 1, 1)),  # Nowruz 1404
        (date(2026, 3, 20), (1404, 12, 29)),  # last day of a 29-day Esfand
        (date(2026, 3, 21), (1405, 1, 1)),  # Nowruz 1405
        (date(2026, 10, 14), (1405, 7, 22)),
        (date(2026, 12, 21), (1405, 9, 30)),  # Yalda
        (date(2027, 3, 21), (1406, 1, 1)),
        (date(2024, 3, 19), (1402, 12, 29)),
        (date(2025, 3, 20), (1403, 12, 30)),  # 1403 is a leap year: 30 Esfand
    ],
)
def test_jalali_dates(day, jalali):
    assert game.to_jalali(day) == jalali


@pytest.mark.parametrize(
    ("day", "name"),
    [
        (date(2026, 12, 21), "yalda"),
        (date(2026, 3, 17), "chaharshanbe_suri"),  # the Tuesday before the last Wednesday of 1404
        (date(2026, 3, 10), None),  # an earlier Tuesday in Esfand
        (date(2026, 3, 21), "nowruz"),
        (date(2026, 4, 1), "nowruz"),  # 12 Farvardin
        (date(2026, 4, 2), "sizdah_bedar"),
        (date(2026, 4, 3), None),
        (date(2026, 10, 14), None),
    ],
)
def test_holidays(day, name):
    h = game.holiday(day)
    assert (h.name if h else None) == name


def test_lucky_hour_is_daytime_stable_and_differs_between_bots():
    days = [date(2026, 10, 1) + timedelta(days=i) for i in range(60)]
    for d in days:
        h = game.lucky_hour("cat", d)
        assert 9 <= h <= 22 and h == game.lucky_hour("cat", d)
    assert [game.lucky_hour("cat", d) for d in days] != [game.lucky_hour("chai", d) for d in days]


def _lucky_moment(bot: str, day: date) -> datetime:
    hour = game.lucky_hour(bot, day)
    local = datetime(day.year, day.month, day.day, hour, 15, tzinfo=game.TZ)
    return local.astimezone(timezone.utc)


def test_active_boosts_during_and_outside_the_lucky_hour():
    day = date(2026, 10, 14)
    at = _lucky_moment("cat", day)
    assert [b.name for b in game.active_boosts("cat", at)] == ["lucky_hour"]
    assert game.active_boosts("cat", at + timedelta(hours=1)) == ()


def test_gains_are_doubled_and_losses_are_not():
    rng = random.Random(1)
    for _ in range(2000):
        r = game.roll(CAT, 0, rng, (game.LUCKY_HOUR,))
        if r.event == "lost_turn":
            continue
        raw = r.base + r.bonus
        assert r.points == (raw * 2 if raw > 0 else raw)


def test_boosts_stack():
    r = game.roll(CAT, 0, random.Random(4), (game.LUCKY_HOUR, game.YALDA))
    assert r.multiplier == 4 and r.boosts == ("lucky_hour", "yalda")


def test_sizdah_bedar_has_no_losses():
    rng = random.Random(2)
    rolls = [game.roll(CAT, 0, rng, (game.SIZDAH_BEDAR,)) for _ in range(5000)]
    assert all(r.points >= 0 for r in rolls)
    assert all(r.event != "bad" for r in rolls)


def test_nowruz_makes_rare_events_more_likely():
    rng = random.Random(3)
    n = 20_000
    rare = sum(game.roll(CAT, 0, rng, (game.NOWRUZ,)).event in ("good", "bad") for _ in range(n)) / n
    assert 0.13 < rare < 0.17


def test_banners_render_in_both_languages():
    r = game.Roll(5, 0, None, CAT.gains[0], ("lucky_hour", "nowruz"), 2)
    out = texts.play_result(CAT_BOTH, "Simin", service.Played(r, 10, 160, 0, 1, CAT.cooldown))
    assert "ساعت شانس" in out and "Lucky hour" in out and "نوروز" in out and "+10 g" in out


async def test_play_during_the_lucky_hour_carries_the_boost(store):
    at = _lucky_moment("cat", date(2026, 10, 14))
    r = await service.play(
        store, CAT, chat_id=CHAT, chat_title="g", user_id=1, username="u", first_name="U",
        now=at, rng=random.Random(5),
    )
    assert "lucky_hour" in r.roll.boosts


# --- Weekly champion -----------------------------------------------------------------

SUNDAY_EVENING = datetime(2026, 10, 18, 18, 30, tzinfo=timezone.utc)  # 20:30 in Rome


class FakeBot:
    def __init__(self, fail_for: set[int] = frozenset()):
        self.sent: list[tuple[int, str]] = []
        self.fail_for = fail_for

    async def send_message(self, chat_id, text):
        if chat_id in self.fail_for:
            from aiogram.exceptions import TelegramForbiddenError
            raise TelegramForbiddenError(method=None, message="bot was kicked")
        self.sent.append((chat_id, text))


async def _week_of_plays(store, theme, chat_id, deltas_by_user, when):
    await store.touch_chat(theme.name, chat_id, "g")
    for user_id, deltas in deltas_by_user.items():
        await store.ensure_player(theme.name, chat_id, user_id, f"u{user_id}", f"Player{user_id}", theme.score.start)
        total = theme.score.start + sum(deltas)
        await store.pool.execute(
            "UPDATE players SET score = $1, last_play_at = $2 WHERE bot = $3 AND chat_id = $4 AND user_id = $5",
            total, when, theme.name, chat_id, user_id,
        )
        for d in deltas:
            await store.pool.execute(
                "INSERT INTO plays (bot, chat_id, user_id, delta, score_after, created_at) VALUES ($1,$2,$3,$4,0,$5)",
                theme.name, chat_id, user_id, d, when,
            )


def test_post_time_is_sunday_evening_in_rome():
    assert champion.is_due(SUNDAY_EVENING)
    assert not champion.is_due(SUNDAY_EVENING - timedelta(hours=1))  # 19:30 in Rome
    assert not champion.is_due(SUNDAY_EVENING - timedelta(days=1))


async def test_weekly_report_ranks_the_weeks_movers(store):
    await _week_of_plays(store, CAT, CHAT, {1: [10, 5], 2: [30], 3: [-8]}, SUNDAY_EVENING - timedelta(days=2))
    report = await service.weekly_report(store, CAT, chat_id=CHAT, now=SUNDAY_EVENING)
    assert [(p.user_id, g) for p, g in report.movers] == [(2, 30), (1, 15)]  # nobody who went backwards
    out = texts.weekly_champion(CAT_BOTH, report)
    assert "Player2" in out and "+30 g" in out and "قهرمان این هفته" in out


async def test_weekly_report_for_lower_is_better(store):
    await _week_of_plays(store, KONKUR, CHAT, {1: [-3000], 2: [-9000], 3: [5000]}, SUNDAY_EVENING - timedelta(days=1))
    report = await service.weekly_report(store, KONKUR, chat_id=CHAT, now=SUNDAY_EVENING)
    assert [p.user_id for p, _ in report.movers] == [2, 1]
    assert report.leader.user_id == 2


async def test_old_plays_and_quiet_groups_are_skipped(store):
    await _week_of_plays(store, CAT, CHAT, {1: [10]}, SUNDAY_EVENING - timedelta(days=8))
    assert await service.weekly_report(store, CAT, chat_id=CHAT, now=SUNDAY_EVENING) is None
    bot = FakeBot()
    assert await champion.post_champions(bot, CAT, store, SUNDAY_EVENING) == 0


async def test_each_group_is_posted_once_and_a_kicked_bot_does_not_stop_the_rest(store):
    when = SUNDAY_EVENING - timedelta(days=1)
    await _week_of_plays(store, CAT, CHAT, {1: [10]}, when)
    await _week_of_plays(store, CAT, -100888, {1: [7]}, when)
    bot = FakeBot(fail_for={-100888})
    assert await champion.post_champions(bot, CAT, store, SUNDAY_EVENING) == 1
    assert [c for c, _ in bot.sent] == [CHAT]
    # A second run the same evening (the cron job after the runner) posts nothing.
    assert await champion.post_champions(bot, CAT, store, SUNDAY_EVENING + timedelta(minutes=30)) == 0
    # Next Sunday it posts again.
    await _week_of_plays(store, CAT, CHAT, {1: [4]}, SUNDAY_EVENING + timedelta(days=6))
    assert await champion.post_champions(bot, CAT, store, SUNDAY_EVENING + timedelta(days=7)) == 1
