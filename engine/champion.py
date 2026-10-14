"""The weekly champion post: every Sunday evening each group hears who did best that week.

The polling runner (engine.main) checks every few minutes and posts once the time comes.
On Render, where the web service may be asleep, scripts/weekly_champion.py does the same
from a cron job. A group is claimed in the database before posting, so it never gets the
same week's post twice, whichever of them runs first.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from engine import game, service, texts
from engine.db import Store
from engine.theme import Theme

log = logging.getLogger(__name__)

POST_WEEKDAY = 6  # Sunday
POST_HOUR = 20  # 20:00, Europe/Rome
CHECK_EVERY = timedelta(minutes=5)


def is_due(now: datetime) -> bool:
    local = now.astimezone(game.TZ)
    return local.weekday() == POST_WEEKDAY and local.hour >= POST_HOUR


async def post_champions(bot: Bot, theme: Theme, store: Store, now: datetime) -> int:
    """Post this week's champion to every group that played this week. Returns posts sent."""
    today = game.local_day(now)
    sent = 0
    for chat_id in await store.active_chats(theme.name, now - timedelta(days=7)):
        report = await service.weekly_report(store, theme, chat_id=chat_id, now=now)
        if report is None or not await store.claim_champion_post(theme.name, chat_id, today):
            continue
        try:
            await bot.send_message(chat_id, texts.weekly_champion(theme, report))
            sent += 1
        except TelegramAPIError as e:  # removed from the group, group deleted, ...
            log.warning("Weekly champion for %s in %s failed: %s", theme.name, chat_id, e)
    return sent


async def champion_loop(bots: list[tuple[Bot, Theme]], store: Store) -> None:
    """Run forever next to the polling bots, posting each Sunday evening."""
    while True:
        now = datetime.now(timezone.utc)
        if is_due(now):
            for bot, theme in bots:
                try:
                    if n := await post_champions(bot, theme, store, now):
                        log.info("Posted %d weekly champion message(s) for %s", n, theme.name)
                except Exception:
                    log.exception("Weekly champion for %s failed", theme.name)
        await asyncio.sleep(CHECK_EVERY.total_seconds())
