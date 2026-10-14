"""Postgres access. All bots share the same tables; every query is scoped by `bot`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


@dataclass(frozen=True)
class Player:
    user_id: int
    username: str | None
    first_name: str | None
    score: int
    streak: int
    last_play_at: datetime | None
    last_play_date: date | None
    last_duel_at: datetime | None = None


_PLAYER_COLS = "user_id, username, first_name, score, streak, last_play_at, last_play_date, last_duel_at"


@dataclass(frozen=True)
class Duel:
    id: int
    chat_id: int
    challenger_id: int
    target_id: int
    stake: int
    status: str
    winner_id: int | None
    created_at: datetime


_DUEL_COLS = "id, chat_id, challenger_id, target_id, stake, status, winner_id, created_at"


@dataclass(frozen=True)
class Settled:
    duel: Duel
    winner: Player
    loser: Player


@dataclass(frozen=True)
class Blocked:
    """A duel that couldn't be settled; it stays pending."""

    reason: str  # "short": can't cover the stake any more; "cooldown": dueled too recently
    player: Player


def _player(row: asyncpg.Record | None) -> Player | None:
    return Player(**dict(row)) if row else None


def _duel(row: asyncpg.Record | None) -> Duel | None:
    return Duel(**dict(row)) if row else None


class _Rollback(Exception):
    pass


class Store:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> Store:
        # statement_cache_size=0 keeps asyncpg working behind Supabase's pgbouncer pooler.
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, statement_cache_size=0)
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def migrate(self) -> None:
        """Apply every migration file. They are idempotent, so this is safe to re-run."""
        async with self.pool.acquire() as conn:
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                await conn.execute(path.read_text(encoding="utf-8"))

    async def touch_chat(self, bot: str, chat_id: int, title: str | None) -> int | None:
        """Register the group (or refresh its title).

        Returns the group's own cooldown in minutes, or None to use the theme's.
        """
        return await self.pool.fetchval(
            """
            INSERT INTO chats (bot, chat_id, title) VALUES ($1, $2, $3)
            ON CONFLICT (bot, chat_id) DO UPDATE SET title = COALESCE(EXCLUDED.title, chats.title)
            RETURNING cooldown_minutes
            """,
            bot, chat_id, title,
        )

    async def ensure_player(
        self, bot: str, chat_id: int, user_id: int, username: str | None, first_name: str | None, start: int
    ) -> Player:
        row = await self.pool.fetchrow(
            f"""
            INSERT INTO players (bot, chat_id, user_id, username, first_name, score)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (bot, chat_id, user_id)
                DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name
            RETURNING {_PLAYER_COLS}
            """,
            bot, chat_id, user_id, username, first_name, start,
        )
        return _player(row)

    async def get_player(self, bot: str, chat_id: int, user_id: int) -> Player | None:
        row = await self.pool.fetchrow(
            f"SELECT {_PLAYER_COLS} FROM players WHERE bot = $1 AND chat_id = $2 AND user_id = $3",
            bot, chat_id, user_id,
        )
        return _player(row)

    async def find_player(self, bot: str, chat_id: int, username: str) -> Player | None:
        """Look a member up by @username, which is all a /duel @user mention carries."""
        row = await self.pool.fetchrow(
            f"SELECT {_PLAYER_COLS} FROM players "
            f"WHERE bot = $1 AND chat_id = $2 AND lower(username) = lower($3) "
            f"ORDER BY last_play_at DESC NULLS LAST LIMIT 1",
            bot, chat_id, username.lstrip("@"),
        )
        return _player(row)

    async def try_play(
        self,
        bot: str,
        chat_id: int,
        user_id: int,
        *,
        now: datetime,
        today: date,
        cooldown_minutes: int,
        seen_last_play_at: datetime | None,
        delta: int,
        min_score: int,
        streak: int,
        event: str | None,
    ) -> int | None:
        """Apply one roll, or return None if the cooldown hasn't passed.

        The cooldown check and the score change are one UPDATE, so two quick /play
        taps can't both count. The roll was computed from the row as it was read;
        if another /play landed in between, `last_play_at` no longer matches and
        this one is rejected too.
        """
        async with self.pool.acquire() as conn, conn.transaction():
            score = await conn.fetchval(
                """
                UPDATE players SET
                    score = GREATEST($4::bigint, score + $5::bigint),
                    streak = $6::int,
                    last_play_at = $7::timestamptz,
                    last_play_date = $8::date
                WHERE bot = $1 AND chat_id = $2 AND user_id = $3
                  AND last_play_at IS NOT DISTINCT FROM $9::timestamptz
                  AND (last_play_at IS NULL OR last_play_at <= $7::timestamptz - make_interval(mins => $10::int))
                RETURNING score
                """,
                bot, chat_id, user_id, min_score, delta, streak, now, today, seen_last_play_at, cooldown_minutes,
            )
            if score is None:
                return None
            await conn.execute(
                """
                INSERT INTO plays (bot, chat_id, user_id, delta, event, score_after, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                bot, chat_id, user_id, delta, event, score, now,
            )
            return score

    async def rank_of(self, bot: str, chat_id: int, score: int, higher_is_better: bool) -> int:
        """1 + the number of players strictly ahead. Ties share a rank."""
        better = ">" if higher_is_better else "<"
        ahead = await self.pool.fetchval(
            f"SELECT count(*) FROM players WHERE bot = $1 AND chat_id = $2 "
            f"AND last_play_at IS NOT NULL AND score {better} $3",
            bot, chat_id, score,
        )
        return ahead + 1

    async def player_count(self, bot: str, chat_id: int) -> int:
        return await self.pool.fetchval(
            "SELECT count(*) FROM players WHERE bot = $1 AND chat_id = $2 AND last_play_at IS NOT NULL",
            bot, chat_id,
        )

    async def top(self, bot: str, chat_id: int, higher_is_better: bool, limit: int = 10) -> list[Player]:
        order = "DESC" if higher_is_better else "ASC"
        rows = await self.pool.fetch(
            f"""
            SELECT {_PLAYER_COLS} FROM players
            WHERE bot = $1 AND chat_id = $2 AND last_play_at IS NOT NULL
            ORDER BY score {order}, last_play_at ASC
            LIMIT $3
            """,
            bot, chat_id, limit,
        )
        return [_player(r) for r in rows]

    async def active_chats(self, bot: str, since: datetime) -> list[int]:
        """Groups where someone has played since `since`."""
        rows = await self.pool.fetch(
            "SELECT DISTINCT chat_id FROM plays WHERE bot = $1 AND created_at >= $2", bot, since
        )
        return [r["chat_id"] for r in rows]

    async def weekly_gains(
        self, bot: str, chat_id: int, since: datetime, higher_is_better: bool, limit: int = 3
    ) -> list[tuple[Player, int]]:
        """Players by how much their score moved the good way since `since` (rolls and duels)."""
        order = "DESC" if higher_is_better else "ASC"
        rows = await self.pool.fetch(
            f"""
            SELECT {", ".join("pl." + c.strip() for c in _PLAYER_COLS.split(","))}, sum(p.delta) AS gained
            FROM plays p JOIN players pl USING (bot, chat_id, user_id)
            WHERE p.bot = $1 AND p.chat_id = $2 AND p.created_at >= $3
            GROUP BY pl.bot, pl.chat_id, pl.user_id  -- the primary key, so every player column may be selected
            ORDER BY gained {order}
            LIMIT $4
            """,
            bot, chat_id, since, limit,
        )
        return [(_player({k: v for k, v in dict(r).items() if k != "gained"}), r["gained"]) for r in rows]

    async def claim_champion_post(self, bot: str, chat_id: int, today: date) -> bool:
        """Mark this week's champion post as done; False if it was already posted today."""
        return bool(await self.pool.fetchval(
            """
            UPDATE chats SET champion_posted_on = $3
            WHERE bot = $1 AND chat_id = $2 AND (champion_posted_on IS NULL OR champion_posted_on < $3)
            RETURNING 1
            """,
            bot, chat_id, today,
        ))

    async def create_duel(
        self,
        bot: str,
        chat_id: int,
        challenger_id: int,
        target_id: int,
        stake: int,
        *,
        now: datetime,
        expiry: timedelta,
    ) -> int | None:
        """Open a challenge, or return None if the challenger already has one open."""
        return await self.pool.fetchval(
            """
            INSERT INTO duels (bot, chat_id, challenger_id, target_id, stake, created_at)
            SELECT $1, $2, $3, $4, $5, $6
            WHERE NOT EXISTS (
                SELECT 1 FROM duels
                WHERE bot = $1 AND chat_id = $2 AND challenger_id = $3
                  AND status = 'pending' AND created_at > $6::timestamptz - $7::interval
            )
            RETURNING id
            """,
            bot, chat_id, challenger_id, target_id, stake, now, expiry,
        )

    async def get_duel(self, bot: str, duel_id: int) -> Duel | None:
        row = await self.pool.fetchrow(f"SELECT {_DUEL_COLS} FROM duels WHERE bot = $1 AND id = $2", bot, duel_id)
        return _duel(row)

    async def close_duel(self, bot: str, duel_id: int, status: str, *, now: datetime, expiry: timedelta) -> bool:
        """Mark a pending duel declined or expired. False if it was already answered.

        Declining only works while the duel is still live; expiring only after.
        """
        live = "created_at > $4::timestamptz - $5::interval"
        when = live if status == "declined" else f"NOT ({live})"
        closed = await self.pool.fetchval(
            f"UPDATE duels SET status = $3 WHERE bot = $1 AND id = $2 AND status = 'pending' AND {when} RETURNING id",
            bot, duel_id, status, now, expiry,
        )
        return closed is not None

    async def accept_duel(
        self,
        bot: str,
        duel_id: int,
        *,
        winner_id: int,
        winner_delta: int,
        min_score: int,
        now: datetime,
        expiry: timedelta,
        duel_cooldown_hours: int,
    ) -> Settled | Blocked | None:
        """Settle a duel in one transaction, or return None if it is no longer pending.

        Claiming the duel is a single UPDATE ... WHERE status = 'pending', so a double
        tap on Accept settles it once. Both players' rows are then locked (in id order,
        so two duels sharing a player can't deadlock) and re-checked: either can have
        lost points or fought another duel since the challenge. If a check fails the
        whole transaction rolls back and the duel stays pending.
        """
        async with self.pool.acquire() as conn:
            try:
                async with conn.transaction():
                    duel = _duel(await conn.fetchrow(
                        f"""
                        UPDATE duels SET status = 'accepted', winner_id = $3
                        WHERE bot = $1 AND id = $2 AND status = 'pending'
                          AND created_at > $4::timestamptz - $5::interval
                        RETURNING {_DUEL_COLS}
                        """,
                        bot, duel_id, winner_id, now, expiry,
                    ))
                    if duel is None:
                        return None
                    ids = sorted((duel.challenger_id, duel.target_id))
                    rows = await conn.fetch(
                        f"SELECT {_PLAYER_COLS} FROM players "
                        f"WHERE bot = $1 AND chat_id = $2 AND user_id = ANY($3::bigint[]) "
                        f"ORDER BY user_id FOR UPDATE",
                        bot, duel.chat_id, ids,
                    )
                    players = {r["user_id"]: _player(r) for r in rows}
                    if len(players) < 2:
                        raise _Rollback(None)
                    for user_id in (duel.challenger_id, duel.target_id):
                        p = players[user_id]
                        if p.score - min_score < duel.stake:
                            raise _Rollback(Blocked("short", p))
                        if p.last_duel_at is not None and now - p.last_duel_at < timedelta(hours=duel_cooldown_hours):
                            raise _Rollback(Blocked("cooldown", p))

                    loser_id = duel.target_id if winner_id == duel.challenger_id else duel.challenger_id
                    after = {}
                    for user_id, delta in ((winner_id, winner_delta), (loser_id, -winner_delta)):
                        row = await conn.fetchrow(
                            f"""
                            UPDATE players SET score = score + $4::bigint, last_duel_at = $5
                            WHERE bot = $1 AND chat_id = $2 AND user_id = $3
                            RETURNING {_PLAYER_COLS}
                            """,
                            bot, duel.chat_id, user_id, delta, now,
                        )
                        after[user_id] = _player(row)
                        await conn.execute(
                            """
                            INSERT INTO plays (bot, chat_id, user_id, delta, event, score_after, created_at)
                            VALUES ($1, $2, $3, $4, 'duel', $5, $6)
                            """,
                            bot, duel.chat_id, user_id, delta, row["score"], now,
                        )
                    return Settled(duel, after[winner_id], after[loser_id])
            except _Rollback as e:
                return e.args[0]
