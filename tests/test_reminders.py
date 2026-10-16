"""Private "your turn is ready" reminders: opting in, sending once, opting out."""

from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage, TelegramMethod

from engine import reminders
from test_handlers import CAT, GROUP, SIMIN, FakeSession, _press, _send, harness  # noqa: F401 (fixture)

LATER = timedelta(hours=12, minutes=1)


def _button(harness) -> str | None:
    markup = harness[2].sent[-1].reply_markup
    return markup.inline_keyboard[0][0].url if markup else None


async def _opt_in(harness) -> str:
    await _send(harness, "/play", user=SIMIN, update_id=1)
    assert _button(harness) == f"https://t.me/CatTestBot?start=r{GROUP.id}"
    return await _send(harness, f"/start r{GROUP.id}", chat_type="private", user=SIMIN, update_id=2)


async def test_button_turns_reminders_on_in_private(harness):
    reply = await _opt_in(harness)
    assert "حله" in reply and escape(GROUP.title) in reply and "۱۲ ساعت" in reply
    row = await harness[3].pool.fetchrow("SELECT remind, remind_at, last_play_at FROM players WHERE user_id = 7")
    assert row["remind"] and row["remind_at"] == row["last_play_at"] + timedelta(hours=12)


async def test_reminder_is_sent_once_when_due(harness):
    dp, bot, session, store = harness
    await _opt_in(harness)
    bots = {"cat": (bot, CAT)}
    now = datetime.now(timezone.utc)
    assert await reminders.send_due(bots, store, now) == 0  # not yet

    before = len(session.sent)
    assert await reminders.send_due(bots, store, now + LATER) == 1
    ping = session.sent[-1]
    assert ping.chat_id == SIMIN.id and "نوبتت" in ping.text and escape(GROUP.title) in ping.text
    assert len(session.sent) == before + 1
    assert await reminders.send_due(bots, store, now + LATER) == 0  # sent once only


async def test_no_button_once_reminders_are_on_and_play_resets_the_timer(harness):
    store = harness[3]
    await _opt_in(harness)
    await store.pool.execute("UPDATE players SET last_play_at = last_play_at - interval '13 hours'")
    await _send(harness, "/play", user=SIMIN, update_id=3)
    assert _button(harness) is None
    row = await store.pool.fetchrow("SELECT remind_at, last_play_at FROM players WHERE user_id = 7")
    assert row["remind_at"] == row["last_play_at"] + timedelta(hours=12)


async def test_turn_ready_already(harness):
    await _send(harness, "/play", user=SIMIN, update_id=1)
    await harness[3].pool.execute("UPDATE players SET last_play_at = last_play_at - interval '13 hours'")
    reply = await _send(harness, f"/start r{GROUP.id}", chat_type="private", user=SIMIN, update_id=2)
    assert "الانم نوبتته" in reply


async def test_unknown_group(harness):
    reply = await _send(harness, "/start r-100999", chat_type="private", user=SIMIN, update_id=1)
    assert "اول باید" in reply


async def test_plain_start_still_shows_help(harness):
    assert "/play" in await _send(harness, "/start", chat_type="private")


async def test_stop_button(harness):
    dp, bot, session, store = harness
    await _opt_in(harness)
    await dp.feed_update(bot, _press(session.sent[-1], 0, SIMIN, 3))
    assert "دیگه برای" in session.answers[-1].text
    assert not await store.pool.fetchval("SELECT remind FROM players WHERE user_id = 7")
    assert await reminders.send_due({"cat": (bot, CAT)}, store, datetime.now(timezone.utc) + LATER) == 0


class Blocked(FakeSession):
    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        if isinstance(method, SendMessage):
            raise TelegramForbiddenError(method, "bot was blocked by the user")
        return await super().make_request(bot, method, timeout)


async def test_blocked_bot_stops_reminders(harness):
    _, bot, _, store = harness
    await _opt_in(harness)
    blocked = Bot(bot.token, session=Blocked())
    assert await reminders.send_due({"cat": (blocked, CAT)}, store, datetime.now(timezone.utc) + LATER) == 0
    assert not await store.pool.fetchval("SELECT remind FROM players WHERE user_id = 7")
