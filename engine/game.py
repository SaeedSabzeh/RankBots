"""Pure game rules: rolls, streaks, titles, boosts. No I/O, so it is easy to unit test.

All numbers are starting values from the plan, to tune after a week of real play.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from engine.theme import Text, Theme, Title

# Calendar days for streaks are counted in this time zone.
TZ = ZoneInfo("Europe/Rome")

# Each roll is a gain, a loss or neutral with these odds; the sentence picked sets the points.
GAIN_SHARE, LOSS_SHARE = 10 / 16, 5 / 16  # the remaining 1/16 is neutral
EVENT_CHANCE = 0.05
STREAK_DAYS_PER_BONUS = 3
STREAK_BONUS_CAP = 5
DUEL_COOLDOWN_HOURS = 6
DUEL_EXPIRY = timedelta(minutes=10)
# Stake buttons offered by /duel, in score units before the theme's scale (konkur: x1000).
DUEL_STAKES = (5, 10, 25, 50)


@dataclass(frozen=True)
class Roll:
    # Points are "good for the player" units: positive always helps, whatever the
    # theme's direction. score_delta() turns them into a change of the score.
    base: int
    bonus: int
    # "lost_turn" is the theme hook firing: no points, but the turn is used.
    event: Literal["good", "bad", "lost_turn"] | None
    message: Text
    # Boosts active for this roll (lucky hour, holidays), shown as banners.
    boosts: tuple[str, ...] = ()
    # Gains are multiplied by this (lucky hour, Yalda); losses never are.
    multiplier: int = 1

    @property
    def line_points(self) -> int:
        """The sentence's own points, doubled by boosts when it's a gain."""
        return self.base * self.multiplier if self.base > 0 else self.base

    @property
    def points(self) -> int:
        return self.line_points + self.bonus


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


def roll(theme: Theme, streak: int, rng: random.Random, boosts: tuple[Boost, ...] = ()) -> Roll:
    hook = theme.hook
    if hook is not None and hook.kind == "lost_turn" and rng.random() < hook.chance:
        return Roll(base=0, bonus=0, event="lost_turn", message=rng.choice(hook.messages))

    names = tuple(b.name for b in boosts)
    multiplier = 1
    for b in boosts:
        multiplier *= b.gain_multiplier
    no_losses = any(b.no_losses for b in boosts)
    event_chance = max([EVENT_CHANCE, *(b.event_chance for b in boosts)])

    bonus = streak_bonus(streak)
    if rng.random() < event_chance:
        kind: Literal["good", "bad"] = "good" if no_losses else rng.choice(("good", "bad"))
        line = rng.choice(theme.events.good if kind == "good" else theme.events.bad)
        return Roll(int(line["n"]), bonus, kind, line, names, multiplier)

    # Every sentence carries its own fixed points, so the number always fits the joke.
    u = rng.random()
    if u < GAIN_SHARE or (no_losses and u < GAIN_SHARE + LOSS_SHARE):
        pool = theme.gains
    elif u < GAIN_SHARE + LOSS_SHARE:
        pool = theme.losses
    else:
        pool = theme.neutral or theme.gains
    line = rng.choice(pool)
    return Roll(int(line.get("n", 0)), bonus, None, line, names, multiplier)


# --- Boosts: the daily lucky hour and Persian holidays ---------------------------


@dataclass(frozen=True)
class Boost:
    name: str
    gain_multiplier: int = 1
    event_chance: float = 0.0
    no_losses: bool = False


LUCKY_HOUR = Boost("lucky_hour", gain_multiplier=2)
YALDA = Boost("yalda", gain_multiplier=2)
CHAHARSHANBE_SURI = Boost("chaharshanbe_suri", event_chance=0.20)
NOWRUZ = Boost("nowruz", event_chance=0.15)
SIZDAH_BEDAR = Boost("sizdah_bedar", no_losses=True)
# The lucky hour falls between 9:00 and 22:59, when people are awake.
LUCKY_FIRST_HOUR, LUCKY_HOURS = 9, 14


def lucky_hour(bot: str, day: date) -> int:
    """Each bot's secret lucky hour for a day: same for everyone, different every day."""
    digest = hashlib.sha256(f"{bot}:{day.isoformat()}".encode()).digest()
    return LUCKY_FIRST_HOUR + int.from_bytes(digest[:4], "big") % LUCKY_HOURS


def holiday(day: date) -> Boost | None:
    """The Persian holiday on this (Rome) calendar day, if any."""
    _, month, dom = to_jalali(day)
    if month == 9 and dom == 30:
        return YALDA  # Shab-e Yalda, the last night of Azar
    if month == 12 and day.weekday() == 1 and to_jalali(day + timedelta(days=7))[1] == 1:
        return CHAHARSHANBE_SURI  # the eve of the last Wednesday of the year
    if month == 1 and dom == 13:
        return SIZDAH_BEDAR
    if month == 1 and dom <= 12:
        return NOWRUZ
    return None


def active_boosts(bot: str, now: datetime) -> tuple[Boost, ...]:
    local = now.astimezone(TZ)
    boosts = []
    if local.hour == lucky_hour(bot, local.date()):
        boosts.append(LUCKY_HOUR)
    if (h := holiday(local.date())) is not None:
        boosts.append(h)
    return tuple(boosts)


# --- Persian (Jalali) calendar, after the jalaali-js algorithm --------------------

_BREAKS = (-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324,
           2394, 2456, 3178)


def _div(a: int, b: int) -> int:
    return int(a / b)  # truncates toward zero, like the JavaScript original


def _mod(a: int, b: int) -> int:
    return a - _div(a, b) * b


def _jal_cal(jy: int) -> tuple[int, int]:
    """(years since the last leap year, the March day Farvardin 1 falls on) for a Jalali year."""
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    for jm in _BREAKS[1:]:
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j += _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return leap, march


def to_jalali(day: date) -> tuple[int, int, int]:
    """Gregorian date to (year, month, day) in the Persian calendar."""
    jy = day.year - 621
    leap, march = _jal_cal(jy)
    k = day.toordinal() - date(day.year, 3, march).toordinal()
    if k >= 0:
        if k <= 185:
            return jy, 1 + k // 31, k % 31 + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + k // 30, k % 30 + 1


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


def duel_stake_options(theme: Theme, *headrooms: int) -> list[int]:
    """Stake buttons both players can afford; if none of the presets fit, their whole headroom."""
    cap = min(headrooms)
    if cap <= 0:
        return []
    options = [s * theme.score.scale for s in DUEL_STAKES if s * theme.score.scale <= cap]
    return options or [cap]


def duel_winner_delta(theme: Theme, stake: int) -> int:
    """The winner's score change; the loser's is the opposite. Stakes are not scaled."""
    return stake if theme.higher_is_better else -stake


def title_for(theme: Theme, score: int) -> Title:
    reached = [t for t in theme.titles if theme.reaches(score, t.at)]
    return reached[-1] if reached else theme.titles[0]


def cooldown_left(last_play_at: datetime | None, cooldown: timedelta, now: datetime) -> timedelta:
    """Time until the next /play is allowed; zero or negative means play now."""
    if last_play_at is None:
        return timedelta(0)
    return last_play_at + cooldown - now
