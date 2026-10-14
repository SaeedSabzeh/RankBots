"""Telegram command handlers, shared by every bot.

One Dispatcher serves all bots. A middleware puts the right `theme` into each update,
picked by which bot received it, so handlers never know which bot they are.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.enums import ChatType, MessageEntityType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from engine import service, texts
from engine.db import Store
from engine.theme import Theme

_rng = random.SystemRandom()
log = logging.getLogger(__name__)

# Short-lived replies ("not yet", refused duels, ...) and the command that caused them are
# deleted after this many seconds, to keep groups clean. Deleting a member's command needs
# the bot to be a group admin with "Delete messages"; without it only the reply goes.
CLEANUP_AFTER = 60.0
_cleanups: set[asyncio.Task] = set()

GROUPS = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
COMMANDS = {
    "en": [
        BotCommand(command="play", description="Roll once (every {every})"),
        BotCommand(command="me", description="Your score, rank and streak"),
        BotCommand(command="top", description="Group leaderboard"),
        BotCommand(command="duel", description="Duel someone: /duel @user <stake>"),
        BotCommand(command="help", description="Rules and commands"),
    ],
    "fa": [
        BotCommand(command="play", description="بازی کن (هر {every})"),
        BotCommand(command="me", description="امتیاز، رتبه و روزهای پشت سر هم"),
        BotCommand(command="top", description="جدول گروه"),
        BotCommand(command="duel", description="دوئل: /duel @user <امتیاز>"),
        BotCommand(command="help", description="قوانین و دستورها"),
    ],
}


class DuelButton(CallbackData, prefix="duel"):
    duel_id: int
    accept: bool


class ThemeMiddleware(BaseMiddleware):
    """Injects the theme of the bot that received the update."""

    def __init__(self, themes_by_bot_id: dict[int, Theme]):
        self.themes_by_bot_id = themes_by_bot_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["theme"] = self.themes_by_bot_id[data["bot"].id]
        return await handler(event, data)


async def set_commands(bot: Bot, theme: Theme) -> None:
    def commands(lang: str) -> list[BotCommand]:
        every = texts.duration(theme.cooldown, lang)
        return [c.model_copy(update={"description": c.description.format(every=every)}) for c in COMMANDS[lang]]

    await bot.set_my_commands(commands(theme.langs[0]))
    for lang in theme.langs:
        await bot.set_my_commands(commands(lang), language_code=lang)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _delete_later(bot: Bot, chat_id: int, message_ids: list[int], delay: float) -> None:
    await asyncio.sleep(delay)
    for message_id in message_ids:
        try:
            await bot.delete_message(chat_id, message_id)
        except TelegramAPIError as e:  # already deleted, too old, or no admin rights
            log.debug("Could not delete %s in %s: %s", message_id, chat_id, e)


def delete_later(bot: Bot, chat_id: int, *message_ids: int) -> None:
    """Delete these messages after CLEANUP_AFTER seconds, without waiting for it."""
    task = asyncio.create_task(_delete_later(bot, chat_id, list(message_ids), CLEANUP_AFTER))
    _cleanups.add(task)  # keep a reference so the task isn't garbage-collected
    task.add_done_callback(_cleanups.discard)


async def reply_briefly(message: Message, text: str) -> None:
    """Reply, then remove the reply and the command a minute later (groups only)."""
    sent = await message.reply(text)
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        delete_later(message.bot, message.chat.id, sent.message_id, message.message_id)


def _name(message: Message) -> str:
    user = message.from_user
    return texts.display_name(user.first_name, user.username)


async def cmd_help(message: Message, theme: Theme) -> None:
    await message.reply(texts.help_text(theme))


async def cmd_private(message: Message, theme: Theme) -> None:
    await message.reply(texts.group_only(theme))


async def cmd_play(message: Message, theme: Theme, store: Store) -> None:
    user = message.from_user
    result = await service.play(
        store, theme,
        chat_id=message.chat.id, chat_title=message.chat.title,
        user_id=user.id, username=user.username, first_name=user.first_name,
        now=_now(), rng=_rng,
    )
    if isinstance(result, service.OnCooldown):
        await reply_briefly(message, texts.cooldown(theme, _name(message), result.left))
    else:
        await message.reply(texts.play_result(theme, _name(message), result))


async def cmd_me(message: Message, theme: Theme, store: Store) -> None:
    st = await service.stats(store, theme, chat_id=message.chat.id, user_id=message.from_user.id, now=_now())
    if st is None:
        await reply_briefly(message, texts.not_played(theme, _name(message)))
    else:
        await message.reply(texts.me(theme, _name(message), st))


async def cmd_top(message: Message, theme: Theme, store: Store) -> None:
    b = await service.board(store, theme, chat_id=message.chat.id, user_id=message.from_user.id)
    await message.reply(texts.top(theme, b))


def _stake(token: str) -> int | None:
    # \d also matches Persian digits, and int() reads them: "۵۰" is 50.
    return int(token) if re.fullmatch(r"\d+", token) else None


def _duel_target(message: Message) -> service.Who | str | None:
    """Who /duel is aimed at: an @mention, a mention of a user without a username, or a reply."""
    for e in message.entities or []:
        if e.type == MessageEntityType.TEXT_MENTION and e.user:
            return service.Who(e.user.id, e.user.username, e.user.first_name, e.user.is_bot)
        if e.type == MessageEntityType.MENTION:
            return e.extract_from(message.text)
    reply = message.reply_to_message
    # In forum groups every message "replies" to its topic's first message; that isn't a target.
    if reply and reply.from_user and not reply.forum_topic_created:
        u = reply.from_user
        return service.Who(u.id, u.username, u.first_name, u.is_bot)
    return None


async def cmd_duel(message: Message, command: CommandObject, theme: Theme, store: Store) -> None:
    args = (command.args or "").split()
    stake = _stake(args[-1]) if args else None
    target = _duel_target(message)
    if not stake or target is None:
        await reply_briefly(message, texts.duel_usage(theme))
        return

    user = message.from_user
    result = await service.challenge(
        store, theme,
        chat_id=message.chat.id, chat_title=message.chat.title,
        challenger=service.Who(user.id, user.username, user.first_name),
        target=target, stake=stake, now=_now(),
    )
    if isinstance(result, service.DuelRefused):
        await reply_briefly(message, texts.duel_refused(theme, result))
        return
    accept, decline = texts.duel_buttons(theme)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=accept, callback_data=DuelButton(duel_id=result.duel_id, accept=True).pack()),
        InlineKeyboardButton(text=decline, callback_data=DuelButton(duel_id=result.duel_id, accept=False).pack()),
    ]])
    await message.reply(texts.duel_offer(theme, result), reply_markup=keyboard)


async def on_duel_button(query: CallbackQuery, callback_data: DuelButton, theme: Theme, store: Store) -> None:
    result = await service.answer_duel(
        store, theme,
        duel_id=callback_data.duel_id, user_id=query.from_user.id, accept=callback_data.accept,
        now=_now(), rng=_rng,
    )
    if isinstance(result, service.NotYourDuel):
        await query.answer(texts.duel_popup(theme, "duel_not_yours"), show_alert=True)
    elif isinstance(result, service.DuelGone):
        await query.answer(texts.duel_popup(theme, "duel_gone"), show_alert=True)
    elif isinstance(result, service.DuelRefused):
        # Someone can't cover the stake or dueled elsewhere; the challenge stays open.
        await query.answer(texts.popup(texts.duel_refused(theme, result)), show_alert=True)
    else:
        if isinstance(result, service.DuelResult):
            text = texts.duel_result(theme, result)
        else:
            text = texts.duel_closed(theme, result)
        if isinstance(query.message, Message):
            await query.message.edit_text(text, reply_markup=None)
            if isinstance(result, service.DuelClosed):
                # A declined or expired challenge is clutter: clear it and the /duel command.
                ids = [query.message.message_id]
                if query.message.reply_to_message is not None:
                    ids.append(query.message.reply_to_message.message_id)
                delete_later(query.bot, query.message.chat.id, *ids)
        await query.answer()


def build_dispatcher(store: Store, themes_by_bot_id: dict[int, Theme]) -> Dispatcher:
    router = Router()
    router.message.register(cmd_help, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_private, Command("play", "me", "top", "duel"), ~GROUPS)
    router.message.register(cmd_play, Command("play"), GROUPS)
    router.message.register(cmd_me, Command("me"), GROUPS)
    router.message.register(cmd_top, Command("top"), GROUPS)
    router.message.register(cmd_duel, Command("duel"), GROUPS)
    router.callback_query.register(on_duel_button, DuelButton.filter())

    dp = Dispatcher(store=store)
    dp.update.outer_middleware(ThemeMiddleware(themes_by_bot_id))
    dp.include_router(router)
    return dp
