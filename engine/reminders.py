"""Private "your turn is ready" messages, for players who asked for them.

A player opts in per bot and group with the button under /play, which opens the bot's private
chat (a bot can only message people who started it). Each /play then sets `remind_at` to when the
turn is ready, and send_due() sends what is due. It runs every 30 seconds while the service is up;
on Render's free plan, where the service sleeps, a Supabase pg_cron job calls /tick to wake it
when a reminder is due (supabase/reminder_wakeup.sql).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from engine import texts
from engine.db import Store
from engine.theme import Theme

log = logging.getLogger(__name__)

CHECK_EVERY = timedelta(seconds=30)


class StopReminders(CallbackData, prefix="rs"):
    chat_id: int


def start_link(bot_username: str, chat_id: int) -> str:
    """Opens the bot's private chat and sends /start r<chat_id>, which turns reminders on."""
    return f"https://t.me/{bot_username}?start=r{chat_id}"


def stop_keyboard(theme: Theme, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=texts.label(theme, "remind_stop_button"), callback_data=StopReminders(chat_id=chat_id).pack())]])


async def send_due(bots: dict[str, tuple[Bot, Theme]], store: Store, now: datetime) -> int:
    """Send every reminder that is due. Returns how many were sent."""
    sent = 0
    for r in await store.take_due_reminders(list(bots), now):
        bot, theme = bots[r.bot]
        try:
            await bot.send_message(r.user_id, texts.reminder(theme, r.first_name, r.title),
                                   reply_markup=stop_keyboard(theme, r.chat_id))
            sent += 1
        except TelegramForbiddenError:
            # They blocked the bot or deleted the chat: stop trying.
            await store.stop_all_reminders(r.bot, r.user_id)
        except TelegramAPIError as e:
            log.warning("Reminder for %s from %s failed: %s", r.user_id, r.bot, e)
    return sent


async def reminder_loop(bots: dict[str, tuple[Bot, Theme]], store: Store) -> None:
    """Run forever next to the bots."""
    while True:
        try:
            if n := await send_due(bots, store, datetime.now(timezone.utc)):
                log.info("Sent %d reminder(s)", n)
        except Exception:
            log.exception("Sending reminders failed")
        await asyncio.sleep(CHECK_EVERY.total_seconds())
