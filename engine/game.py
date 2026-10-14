"""Pure game rules: rolls, streaks, titles. No I/O, so it is easy to unit test.

All numbers are starting values from the plan, to tune after a week of real play.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from engine.theme import Text, Theme, Title

# Calendar days for streaks are counted in this time zone.
TZ = ZoneInfo("Europe/Rome")

DEFAULT_COOLDOWN_HOURS = 12
ROLL_MIN, ROLL_MAX = -5, 10
EVENT_CHANCE = 0.05
EVENT_MIN, EVENT_MAX = 20, 50
STREAK_DAYS_PER_BONUS = 3
STREAK_BONUS_CAP = 5
DUEL_COOLDOWN_HOURS = 6
DUEL_EXPIRY = timedelta(minutes=10)


@dataclass(frozen=True)
class Roll:
    # Points are "good for the player" units: positive always helps, whatever the
    # theme's direction. score_delta() turns them into a change of the score.
    base: int
    bonus: int
    # "lost_turn" is the theme hook firing: no points, but the turn is used.
    event: Literal["good", "bad", "lost_turn"] | None
    message: Text

    @property
    def points(self) -> int:
        return self.base + self.bonus


def local_day(now: datetime) -> date:
    return now.astimezone(TZ).date()


def next_streak(streak: int, last_play_date: date | None, today: date) -> int:
    """Consecutive calendar days raise the streak by 1; a missed day resets it to 0."""
    if last_play_date == today:
        return streak
    if last_play_date == today - timedelta(days=1):
        return streak + 1
    return 0


def live_streak(streak: int, last_play_date: date | None, today: date) -> int:
    """The streak as it stands now: already lost if the last play was before yesterday."""
    if last_play_date is None or last_play_date < today - timedelta(days=1):
        return 0
    return streak


def streak_bonus(streak: int) -> int:
    return min(streak // STREAK_DAYS_PER_BONUS, STREAK_BONUS_CAP)


def roll(theme: Theme, streak: int, rng: random.Random) -> Roll:
    hook = theme.hook
    if hook is not None and hook.kind == "lost_turn" and rng.random() < hook.chance:
        return Roll(base=0, bonus=0, event="lost_turn", message=rng.choice(hook.messages))

    bonus = streak_bonus(streak)
    if rng.random() < EVENT_CHANCE:
        kind: Literal["good", "bad"] = rng.choice(("good", "bad"))
        size = rng.randint(EVENT_MIN, EVENT_MAX)
        pool = theme.events.good if kind == "good" else theme.events.bad
        base = size if kind == "good" else -size
        return Roll(base=base, bonus=bonus, event=kind, message=rng.choice(pool))

    base = rng.randint(ROLL_MIN, ROLL_MAX)
    points = base + bonus
    if points > 0:
        pool = theme.gains
    elif points < 0:
        pool = theme.losses
    else:
        pool = theme.neutral or theme.gains
    return Roll(base=base, bonus=bonus, event=None, message=rng.choice(pool))


def score_delta(theme: Theme, points: int) -> int:
    """The signed change to the stored score for a number of good-for-player points."""
    sign = 1 if theme.higher_is_better else -1
    return points * theme.score.scale * sign


def apply_delta(theme: Theme, score: int, delta: int) -> int:
    """Mirror of the SQL update: add the delta, never past the theme's floor."""
    return max(theme.score.min, score + delta)


def duel_headroom(theme: Theme, score: int) -> int:
    """The largest stake a player can put up in a duel.

    A stake moves the winner and the loser the same distance in opposite directions.
    One of them always moves toward the theme's floor: the loser when higher is
    better, the winner when lower is better (a konkur rank can't improve past 1).
    Allowing at most the distance to the floor, for both players, keeps every duel
    exactly zero-sum in either direction.
    """
    return score - theme.score.min


def duel_winner_delta(theme: Theme, stake: int) -> int:
    """The winner's score change; the loser's is the opposite. Stakes are not scaled."""
    return stake if theme.higher_is_better else -stake


def title_for(theme: Theme, score: int) -> Title:
    reached = [t for t in theme.titles if theme.reaches(score, t.at)]
    return reached[-1] if reached else theme.titles[0]


def cooldown_left(last_play_at: datetime | None, cooldown_hours: int, now: datetime) -> timedelta:
    """Time until the next /play is allowed; zero or negative means play now."""
    if last_play_at is None:
        return timedelta(0)
    return last_play_at + timedelta(hours=cooldown_hours) - now
