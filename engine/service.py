"""The /play, /me, /top and /duel flows, between the Telegram handlers and the database."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from engine import game
from engine.db import Blocked, Player, Store
from engine.theme import Theme


@dataclass(frozen=True)
class Played:
    roll: game.Roll
    delta: int
    score: int
    streak: int
    rank: int
    cooldown: timedelta


@dataclass(frozen=True)
class OnCooldown:
    left: timedelta


@dataclass(frozen=True)
class Stats:
    player: Player
    rank: int
    players: int
    cooldown_left: timedelta


@dataclass(frozen=True)
class Board:
    top: list[Player]
    me: Player | None
    my_rank: int | None
    players: int = 0  # everyone who has played in the group, for the last-place nickname


async def _cooldown(store: Store, theme: Theme, chat_id: int, chat_title: str | None) -> timedelta:
    """The group's own cooldown if it has one, otherwise the theme's."""
    minutes = await store.touch_chat(theme.name, chat_id, chat_title)
    return timedelta(minutes=minutes) if minutes else theme.cooldown


async def play(
    store: Store,
    theme: Theme,
    *,
    chat_id: int,
    chat_title: str | None,
    user_id: int,
    username: str | None,
    first_name: str | None,
    now: datetime,
    rng: random.Random,
) -> Played | OnCooldown:
    cooldown = await _cooldown(store, theme, chat_id, chat_title)
    player = await store.ensure_player(theme.name, chat_id, user_id, username, first_name, theme.score.start)

    left = game.cooldown_left(player.last_play_at, cooldown, now)
    if left > timedelta(0):
        return OnCooldown(left)

    today = game.local_day(now)
    streak = game.next_streak(player.streak, player.last_play_date, today)
    roll = game.roll(theme, streak, rng, game.active_boosts(theme.name, now))
    delta = game.score_delta(theme, roll.points)

    score = await store.try_play(
        theme.name, chat_id, user_id,
        now=now, today=today, cooldown_minutes=int(cooldown.total_seconds() // 60),
        seen_last_play_at=player.last_play_at, delta=delta, min_score=theme.score.min,
        streak=streak, event=roll.event,
    )
    if score is None:
        # Another /play from the same person won the race.
        fresh = await store.get_player(theme.name, chat_id, user_id)
        return OnCooldown(game.cooldown_left(fresh.last_play_at, cooldown, now))

    rank = await store.rank_of(theme.name, chat_id, score, theme.higher_is_better)
    return Played(roll, delta, score, streak, rank, cooldown)


async def stats(store: Store, theme: Theme, *, chat_id: int, user_id: int, now: datetime) -> Stats | None:
    player = await store.get_player(theme.name, chat_id, user_id)
    if player is None or player.last_play_at is None:
        return None
    cooldown = await _cooldown(store, theme, chat_id, None)
    rank = await store.rank_of(theme.name, chat_id, player.score, theme.higher_is_better)
    players = await store.player_count(theme.name, chat_id)
    streak = game.live_streak(player.streak, player.last_play_date, game.local_day(now))
    player = Player(**{**player.__dict__, "streak": streak})
    left = game.cooldown_left(player.last_play_at, cooldown, now)
    return Stats(player, rank, players, left)


async def board(store: Store, theme: Theme, *, chat_id: int, user_id: int, limit: int = 10) -> Board:
    top = await store.top(theme.name, chat_id, theme.higher_is_better, limit)
    players = await store.player_count(theme.name, chat_id) if top else 0
    if any(p.user_id == user_id for p in top):
        return Board(top, None, None, players)
    me = await store.get_player(theme.name, chat_id, user_id)
    if me is None or me.last_play_at is None:
        return Board(top, None, None, players)
    return Board(top, me, await store.rank_of(theme.name, chat_id, me.score, theme.higher_is_better), players)


@dataclass(frozen=True)
class Who:
    """A Telegram user as the handlers see them."""

    user_id: int
    username: str | None
    first_name: str | None
    is_bot: bool = False


@dataclass(frozen=True)
class DuelOffer:
    duel_id: int
    challenger: Player
    target: Player
    stake: int


@dataclass(frozen=True)
class DuelRefused:
    reason: Literal["self", "bot", "unknown", "not_played", "short", "cooldown", "pending"]
    first_name: str | None
    username: str | None
    max_stake: int | None = None
    left: timedelta | None = None


@dataclass(frozen=True)
class DuelResult:
    winner: Player
    loser: Player
    stake: int
    winner_delta: int


@dataclass(frozen=True)
class DuelClosed:
    status: Literal["declined", "expired"]
    challenger: Player
    target: Player


@dataclass(frozen=True)
class NotYourDuel:
    pass


@dataclass(frozen=True)
class DuelGone:
    """Already accepted, declined or expired."""


def _duel_check(theme: Theme, p: Player, stake: int, now: datetime) -> DuelRefused | None:
    headroom = game.duel_headroom(theme, p.score)
    if headroom < stake:
        return DuelRefused("short", p.first_name, p.username, max_stake=max(headroom, 0))
    left = game.cooldown_left(p.last_duel_at, timedelta(hours=game.DUEL_COOLDOWN_HOURS), now)
    if left > timedelta(0):
        return DuelRefused("cooldown", p.first_name, p.username, left=left)
    return None


async def challenge(
    store: Store,
    theme: Theme,
    *,
    chat_id: int,
    chat_title: str | None,
    challenger: Who,
    target: Who | str,
    stake: int,
    now: datetime,
) -> DuelOffer | DuelRefused:
    """Open a duel. `target` is a user from a reply or mention, or a bare @username."""
    await store.touch_chat(theme.name, chat_id, chat_title)
    me = await store.ensure_player(
        theme.name, chat_id, challenger.user_id, challenger.username, challenger.first_name, theme.score.start
    )

    if isinstance(target, str):
        them = await store.find_player(theme.name, chat_id, target)
        if them is None:
            return DuelRefused("unknown", None, target.lstrip("@"))
    else:
        if target.is_bot:
            return DuelRefused("bot", target.first_name, target.username)
        them = await store.get_player(theme.name, chat_id, target.user_id)
        if them is None:
            return DuelRefused("not_played", target.first_name, target.username)

    if them.user_id == me.user_id:
        return DuelRefused("self", me.first_name, me.username)
    for p in (me, them):
        if p.last_play_at is None:
            return DuelRefused("not_played", p.first_name, p.username)
    for p in (me, them):
        refused = _duel_check(theme, p, stake, now)
        if refused:
            return refused

    duel_id = await store.create_duel(
        theme.name, chat_id, me.user_id, them.user_id, stake, now=now, expiry=game.DUEL_EXPIRY
    )
    if duel_id is None:
        return DuelRefused("pending", me.first_name, me.username)
    return DuelOffer(duel_id, me, them, stake)


async def answer_duel(
    store: Store,
    theme: Theme,
    *,
    duel_id: int,
    user_id: int,
    accept: bool,
    now: datetime,
    rng: random.Random,
) -> DuelResult | DuelClosed | DuelRefused | NotYourDuel | DuelGone:
    """The target pressed Accept or Decline. Only the target can answer."""
    duel = await store.get_duel(theme.name, duel_id)
    if duel is None or duel.status != "pending":
        return DuelGone()
    if user_id != duel.target_id:
        return NotYourDuel()

    async def closed(status: Literal["declined", "expired"]) -> DuelClosed | DuelGone:
        if not await store.close_duel(theme.name, duel_id, status, now=now, expiry=game.DUEL_EXPIRY):
            return DuelGone()
        challenger = await store.get_player(theme.name, duel.chat_id, duel.challenger_id)
        target = await store.get_player(theme.name, duel.chat_id, duel.target_id)
        return DuelClosed(status, challenger, target)

    if now - duel.created_at >= game.DUEL_EXPIRY:
        return await closed("expired")
    if not accept:
        return await closed("declined")

    winner_id = rng.choice((duel.challenger_id, duel.target_id))
    delta = game.duel_winner_delta(theme, duel.stake)
    settled = await store.accept_duel(
        theme.name, duel_id,
        winner_id=winner_id, winner_delta=delta, min_score=theme.score.min,
        now=now, expiry=game.DUEL_EXPIRY, duel_cooldown_hours=game.DUEL_COOLDOWN_HOURS,
    )
    if settled is None:
        # Answered or expired between the read above and the claim.
        return DuelGone()
    if isinstance(settled, Blocked):
        refused = _duel_check(theme, settled.player, duel.stake, now)
        return refused or DuelGone()
    return DuelResult(settled.winner, settled.loser, duel.stake, delta)


@dataclass(frozen=True)
class WeeklyReport:
    # The week's biggest movers in the good direction, best first, with how far they moved.
    movers: list[tuple[Player, int]]
    leader: Player | None


async def weekly_report(store: Store, theme: Theme, *, chat_id: int, now: datetime) -> WeeklyReport | None:
    """Who did best this week in one group, or None if nobody moved forward."""
    since = now - timedelta(days=7)
    gains = await store.weekly_gains(theme.name, chat_id, since, theme.higher_is_better)
    movers = [(p, g) for p, g in gains if (g > 0 if theme.higher_is_better else g < 0)]
    if not movers:
        return None
    leader = await store.top(theme.name, chat_id, theme.higher_is_better, 1)
    return WeeklyReport(movers, leader[0] if leader else None)
