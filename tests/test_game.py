import random
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

from engine import game
from engine.theme import Theme, load_themes

CAT = load_themes()["cat"]
TAAROF_TEXT = {"en": "The bot insisted: after you!", "fa": "ربات تعارف کرد: «اول شما!»"}
TAAROF = Theme.model_validate({
    **CAT.model_dump(),
    "name": "taarof",
    "hook": {"kind": "lost_turn", "chance": 0.1, "messages": [TAAROF_TEXT]},
})
KONKUR = CAT.model_copy(
    update={"score": CAT.score.model_copy(update={"start": 500_000, "direction": "lower", "scale": 1000, "min": 1})}
)

D = date(2026, 10, 14)


@pytest.mark.parametrize(
    ("streak", "last", "expected"),
    [
        (0, None, 0),  # first play ever
        (4, D, 4),  # second play the same day keeps the streak
        (4, D - timedelta(days=1), 5),  # yesterday: +1
        (4, D - timedelta(days=2), 0),  # missed a day: reset
    ],
)
def test_next_streak(streak, last, expected):
    assert game.next_streak(streak, last, D) == expected


def test_live_streak_drops_after_a_missed_day():
    assert game.live_streak(5, D, D) == 5
    assert game.live_streak(5, D - timedelta(days=1), D) == 5
    assert game.live_streak(5, D - timedelta(days=2), D) == 0


@pytest.mark.parametrize(("streak", "bonus"), [(0, 0), (2, 0), (3, 1), (8, 2), (15, 5), (40, 5)])
def test_streak_bonus_is_one_per_three_days_capped_at_five(streak, bonus):
    assert game.streak_bonus(streak) == bonus


def test_local_day_uses_rome_time():
    # 23:30 UTC on Oct 14 is already Oct 15 in Rome (UTC+2 in summer time).
    assert game.local_day(datetime(2026, 10, 14, 23, 30, tzinfo=timezone.utc)) == date(2026, 10, 15)


def test_rolls_stay_in_range_and_pick_matching_messages():
    rng = random.Random(1)
    events = Counter()
    for _ in range(20_000):
        r = game.roll(CAT, streak=0, rng=rng)
        events[r.event] += 1
        if r.event is None:
            assert game.ROLL_MIN <= r.base <= game.ROLL_MAX
            if r.points > 0:
                assert r.message in CAT.gains
            elif r.points < 0:
                assert r.message in CAT.losses
            else:
                assert r.message in CAT.neutral
        elif r.event == "good":
            assert game.EVENT_MIN <= r.base <= game.EVENT_MAX
            assert r.message in CAT.events.good
        else:
            assert -game.EVENT_MAX <= r.base <= -game.EVENT_MIN
            assert r.message in CAT.events.bad
    rare = (events["good"] + events["bad"]) / 20_000
    assert 0.04 < rare < 0.06


def test_streak_bonus_is_added_to_the_roll():
    r = game.roll(CAT, streak=9, rng=random.Random(3))
    assert r.bonus == 3
    assert r.points == r.base + 3


def test_scores_grow_on_average():
    rng = random.Random(7)
    mean = sum(game.roll(CAT, 0, rng).points for _ in range(20_000)) / 20_000
    assert 1.5 < mean < 3.5


def test_score_delta_follows_direction_and_scale():
    assert game.score_delta(CAT, 7) == 7
    assert game.score_delta(CAT, -3) == -3
    # Konkur: a good roll lowers the rank, in thousands.
    assert game.score_delta(KONKUR, 7) == -7000
    assert game.score_delta(KONKUR, -3) == 3000


def test_score_never_goes_below_the_floor():
    floor = CAT.score.min
    assert game.apply_delta(CAT, floor + 3, -5) == floor
    assert game.apply_delta(KONKUR, 2000, -7000) == 1


def test_titles_by_tier():
    first, second = CAT.titles[0].at, CAT.titles[1].at
    assert game.title_for(CAT, CAT.score.start).at == first
    assert game.title_for(CAT, second - 1).at == first
    assert game.title_for(CAT, second).at == second
    assert game.title_for(CAT, 10_000).at == CAT.titles[-1].at


def test_cooldown_left():
    now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
    twelve = timedelta(hours=12)
    assert game.cooldown_left(None, twelve, now) == timedelta(0)
    assert game.cooldown_left(now - timedelta(hours=3), twelve, now) == timedelta(hours=9)
    assert game.cooldown_left(now - timedelta(hours=13), twelve, now) < timedelta(0)


def test_each_theme_has_its_own_cooldown():
    themes = load_themes()
    assert themes["chai"].cooldown == timedelta(minutes=5)
    assert themes["cat"].cooldown == timedelta(minutes=90)


def test_durations_read_naturally():
    from engine.texts import duration

    assert duration(timedelta(hours=12), "en") == "12h"
    assert duration(timedelta(hours=9, minutes=3, seconds=10), "en") == "9h 4m"
    assert duration(timedelta(minutes=5), "fa") == "۵ دقیقه"
    assert duration(timedelta(seconds=20), "en") == "1m"


def test_taarof_hook_loses_about_one_turn_in_ten():
    rng = random.Random(5)
    rolls = [game.roll(TAAROF, streak=9, rng=rng) for _ in range(20_000)]
    lost = [r for r in rolls if r.event == "lost_turn"]
    assert 0.09 < len(lost) / len(rolls) < 0.11
    for r in lost:
        # No points at all, not even the streak bonus.
        assert r.points == 0 and r.bonus == 0
        assert r.message == TAAROF_TEXT
    assert all(r.bonus == 3 for r in rolls if r.event != "lost_turn")


def test_themes_without_a_hook_never_lose_a_turn():
    rng = random.Random(5)
    assert all(game.roll(CAT, 0, rng).event != "lost_turn" for _ in range(20_000))


def test_duel_headroom_is_the_distance_to_the_floor():
    assert game.duel_headroom(CAT, CAT.score.min + 40) == 40
    assert game.duel_headroom(KONKUR, 500_000) == 499_999
    assert game.duel_headroom(KONKUR, 1) == 0


def test_duel_winner_moves_in_the_good_direction():
    assert game.duel_winner_delta(CAT, 30) == 30
    # Konkur: winning lowers the rank. Stakes are typed in score units, so no scaling.
    assert game.duel_winner_delta(KONKUR, 30) == -30


def test_konkur_rank_has_no_unit_and_moves_in_thousands():
    from engine.texts import amount

    konkur = load_themes()["konkur"]
    assert konkur.score.start == 500_000 and not konkur.higher_is_better
    assert game.score_delta(konkur, 3) == -3000
    assert amount(konkur, 492_000, "en") == "492,000"
    assert amount(konkur, -3000, "en", signed=True) == "−3,000"
