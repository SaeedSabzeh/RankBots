"""Feed fake Telegram updates through the real dispatcher and capture the replies."""

import re
from datetime import datetime, timezone
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    GetMe,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User

from engine.db import Store
from engine.handlers import build_dispatcher
from engine.theme import load_themes

# These tests use round scores like 50 g, so they run on a cat with a floor of 0.
_CAT = load_themes()["cat"]
CAT = _CAT.model_copy(update={
    "score": _CAT.score.model_copy(update={"start": 0, "min": 0}),
    "titles": [t.model_copy(update={"at": t.at - _CAT.score.start}) for t in _CAT.titles],
})
TOKEN = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
BOT_USER = User(id=123456789, is_bot=True, first_name="Cat", username="CatTestBot")


class FakeSession(BaseSession):
    """Answers Bot API calls locally and remembers every message the bot sent."""

    def __init__(self):
        super().__init__()
        self.sent: list[SendMessage] = []
        self.edits: list[EditMessageText] = []
        self.answers: list[AnswerCallbackQuery] = []
        self.deleted: list[int] = []

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        if isinstance(method, GetMe):
            return BOT_USER
        if isinstance(method, SendMessage):
            self.sent.append(method)
            return Message(
                message_id=len(self.sent) + 1000,
                date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="supergroup"),
                text=method.text,
            )
        if isinstance(method, EditMessageText):
            self.edits.append(method)
            return True
        if isinstance(method, AnswerCallbackQuery):
            self.answers.append(method)
            return True
        if isinstance(method, EditMessageReplyMarkup):
            return True
        if isinstance(method, DeleteMessage):
            self.deleted.append(method.message_id)
            return True
        raise AssertionError(f"unexpected Bot API call: {type(method).__name__}")

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:
        pass


@pytest.fixture
async def harness(pg_uri):
    store = await Store.connect(pg_uri)
    await store.migrate()
    await store.pool.execute("TRUNCATE chats, players, plays, duels")
    session = FakeSession()
    bot = Bot(TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(store, {bot.id: CAT})
    yield dp, bot, session, store
    await store.close()


GROUP = Chat(id=-100555, type="supergroup", title="Simin's group")
SIMIN = User(id=7, is_bot=False, first_name="Simin", username="simin")
ARASH = User(id=8, is_bot=False, first_name="Arash", username="arash")


def _update(
    text: str,
    chat_type: str = "supergroup",
    user_id: int = 7,
    update_id: int = 1,
    user: User | None = None,
    reply_to: User | None = None,
) -> Update:
    user = user or User(id=user_id, is_bot=False, first_name="Simin", username="simin")
    chat = GROUP if chat_type != "private" else Chat(id=user.id, type=chat_type)
    # Telegram marks every @username in the text as a mention entity.
    entities = [MessageEntity(type="mention", offset=m.start(), length=len(m[0])) for m in re.finditer(r"@\w+", text)]
    reply = None
    if reply_to is not None:
        reply = Message(message_id=500, date=datetime.now(timezone.utc), chat=chat, from_user=reply_to, text="hi")
    msg = Message(
        message_id=update_id, date=datetime.now(timezone.utc), chat=chat, from_user=user, text=text,
        entities=entities or None, reply_to_message=reply,
    )
    return Update(update_id=update_id, message=msg)


def _press(sent: SendMessage, button: int, user: User, update_id: int) -> Update:
    """Tap one of the inline buttons under a message the bot sent."""
    data = sent.reply_markup.inline_keyboard[0][button].callback_data
    msg = Message(message_id=900, date=datetime.now(timezone.utc), chat=GROUP, from_user=BOT_USER, text=sent.text)
    query = CallbackQuery(id=str(update_id), from_user=user, chat_instance="ci", message=msg, data=data)
    return Update(update_id=update_id, callback_query=query)


async def _send(harness, text, **kw) -> str:
    dp, bot, session, _ = harness
    before = len(session.sent)
    await dp.feed_update(bot, _update(text, **kw))
    assert len(session.sent) == before + 1, f"no reply to {text!r}"
    return session.sent[-1].text


async def test_play_me_top_in_a_group(harness):
    reply = await _send(harness, "/play")
    assert "Simin" in reply and "پشمالویی" in reply

    assert "هنوز نوبتت نشده" in await _send(harness, "/play", update_id=2)
    assert "رتبه" in await _send(harness, "/me", update_id=3)
    assert "پشمالوترین گربه‌ها" in await _send(harness, "/top", update_id=4)


async def test_command_addressed_to_this_bot(harness):
    assert "Simin" in await _send(harness, "/play@CatTestBot")


async def test_command_for_another_bot_is_ignored(harness):
    dp, bot, session, _ = harness
    await dp.feed_update(bot, _update("/play@SomeOtherBot"))
    assert session.sent == []


async def test_game_commands_need_a_group(harness):
    assert "گروه" in await _send(harness, "/play", chat_type="private")


async def test_help(harness):
    reply = await _send(harness, "/start", chat_type="private")
    assert "/play" in reply and "/duel" in reply


async def _two_players(harness, simin=50, arash=30):
    _, _, _, store = harness
    await _send(harness, "/play", user=SIMIN, update_id=1)
    await _send(harness, "/play", user=ARASH, update_id=2)
    await store.pool.execute("UPDATE players SET score = $1 WHERE user_id = 7", simin)
    await store.pool.execute("UPDATE players SET score = $1 WHERE user_id = 8", arash)


async def test_duel_by_mention_with_buttons(harness):
    dp, bot, session, store = harness
    await _two_players(harness)

    offer = await _send(harness, "/duel @arash 20", user=SIMIN, update_id=3)
    assert "Arash" in offer and "دوئل" in offer
    sent = session.sent[-1]
    assert [b.text for b in sent.reply_markup.inline_keyboard[0]] == ["⚔️ قبول", "🏳️ نه، مرسی"]

    # The challenger can't accept on the target's behalf.
    await dp.feed_update(bot, _press(sent, 0, SIMIN, 4))
    assert session.answers[-1].show_alert and "مال تو نیست" in session.answers[-1].text
    assert session.edits == []

    await dp.feed_update(bot, _press(sent, 0, ARASH, 5))
    assert len(session.edits) == 1 and "برد" in session.edits[0].text
    # Only a rematch button is left under the result.
    assert [b.text for b in session.edits[0].reply_markup.inline_keyboard[0]] == ["⚔️ انتقام!"]
    scores = await store.pool.fetch("SELECT score FROM players ORDER BY user_id")
    assert sorted(r["score"] for r in scores) in ([10, 70], [30, 50])  # 50/50: 50-20 and 30+20, or the reverse

    # The buttons are dead after the duel.
    await dp.feed_update(bot, _press(sent, 1, ARASH, 6))
    assert "تموم شده" in session.answers[-1].text and len(session.edits) == 1


async def test_duel_by_reply_and_decline(harness):
    dp, bot, session, store = harness
    await _two_players(harness)

    await _send(harness, "/duel ۲۰", user=SIMIN, reply_to=ARASH, update_id=3)  # Persian digits work too
    sent = session.sent[-1]
    assert sent.reply_markup is not None
    await dp.feed_update(bot, _press(sent, 1, ARASH, 4))
    assert "قبول نکرد" in session.edits[-1].text
    assert await store.pool.fetchval("SELECT status FROM duels") == "declined"


async def test_duel_refusals(harness):
    await _two_players(harness, arash=5)
    # Anything short of "/duel @user <stake>" gets buttons for the missing part.
    assert "سر چقدر" in await _send(harness, "/duel @arash", user=SIMIN, update_id=3)
    assert "با کی" in await _send(harness, "/duel 20", user=SIMIN, update_id=4)
    assert "سر چقدر" in await _send(harness, "/duel @arash 0", user=SIMIN, update_id=5)
    assert "حداکثر" in await _send(harness, "/duel @arash 20", user=SIMIN, update_id=6)
    assert "نمی‌شناسم" in await _send(harness, "/duel @ghost 1", user=SIMIN, update_id=7)
    assert "ربات" in await _send(harness, "/duel 1", user=SIMIN, reply_to=BOT_USER, update_id=8)
    assert "خودت" in await _send(harness, "/duel @simin 1", user=SIMIN, update_id=9)
    assert "گروه" in await _send(harness, "/duel @arash 1", chat_type="private", update_id=10)


async def test_not_yet_reply_and_command_are_cleaned_up(harness, monkeypatch):
    import asyncio

    from engine import handlers

    monkeypatch.setattr(handlers, "CLEANUP_AFTER", 0)
    _, _, session, _ = harness
    await _send(harness, "/play", update_id=1)
    assert "هنوز نوبتت نشده" in await _send(harness, "/play", update_id=2)
    await asyncio.sleep(0.05)
    not_yet_reply = 1000 + len(session.sent)
    # The "not yet" reply and the second /play go; the real result and first /play stay.
    assert sorted(session.deleted) == sorted([not_yet_reply, 2])


async def test_real_results_are_not_cleaned_up(harness, monkeypatch):
    import asyncio

    from engine import handlers

    monkeypatch.setattr(handlers, "CLEANUP_AFTER", 0)
    _, _, session, _ = harness
    await _send(harness, "/play", update_id=1)
    await _send(harness, "/top", update_id=2)
    await asyncio.sleep(0.05)
    assert session.deleted == []



def _tap(markup, row: int, col: int, user: User, update_id: int, text: str = "") -> Update:
    """Tap a button in any inline keyboard (a sent message or an edit)."""
    data = markup.inline_keyboard[row][col].callback_data
    msg = Message(message_id=901, date=datetime.now(timezone.utc), chat=GROUP, from_user=BOT_USER, text=text)
    query = CallbackQuery(id=str(update_id), from_user=user, chat_instance="ci", message=msg, data=data)
    return Update(update_id=update_id, callback_query=query)


async def test_duel_with_buttons_only(harness):
    dp, bot, session, store = harness
    await _two_players(harness)  # Simin 50, Arash 30

    picker = await _send(harness, "/duel", user=SIMIN, update_id=3)
    assert "با کی" in picker
    who = session.sent[-1].reply_markup
    assert who.inline_keyboard[0][0].text == "Arash"  # Simin isn't offered herself

    # Arash can't drive Simin's picker.
    await dp.feed_update(bot, _tap(who, 0, 0, ARASH, 4))
    assert session.answers[-1].show_alert

    await dp.feed_update(bot, _tap(who, 0, 0, SIMIN, 5))
    stakes = session.edits[-1]
    assert "سر چقدر" in stakes.text
    labels = [b.text for b in stakes.reply_markup.inline_keyboard[0]]
    assert labels == ["۵ گرم", "۱۰ گرم", "۲۵ گرم"]  # 50 is more than Arash's 30

    await dp.feed_update(bot, _tap(stakes.reply_markup, 0, 2, SIMIN, 6))
    offer = session.edits[-1]
    assert "Arash" in offer.text and "۲۵" in offer.text
    assert len(offer.reply_markup.inline_keyboard[0]) == 2  # Accept / Decline
    assert await store.pool.fetchval("SELECT stake FROM duels WHERE status = 'pending'") == 25


async def test_duel_picker_cancel_cleans_up(harness, monkeypatch):
    import asyncio

    from engine import handlers

    monkeypatch.setattr(handlers, "CLEANUP_AFTER", 0)
    dp, bot, session, _ = harness
    await _two_players(harness)
    await _send(harness, "/duel", user=SIMIN, update_id=3)
    who = session.sent[-1].reply_markup
    await dp.feed_update(bot, _tap(who, len(who.inline_keyboard) - 1, 0, SIMIN, 4))
    await asyncio.sleep(0.05)
    assert 901 in session.deleted


async def test_duel_picker_with_nobody_else(harness):
    await _send(harness, "/play", user=SIMIN, update_id=1)
    assert "کس دیگه‌ای" in await _send(harness, "/duel", user=SIMIN, update_id=2)



async def test_rematch_button_for_the_loser_only(harness):
    dp, bot, session, store = harness
    await _two_players(harness)  # Simin 50, Arash 30
    await _send(harness, "/duel @arash 10", user=SIMIN, update_id=3)
    await dp.feed_update(bot, _press(session.sent[-1], 0, ARASH, 4))  # Arash accepts
    result = session.edits[-1]
    winner_id = await store.pool.fetchval("SELECT winner_id FROM duels")
    winner, loser = (SIMIN, ARASH) if winner_id == SIMIN.id else (ARASH, SIMIN)

    await dp.feed_update(bot, _tap(result.reply_markup, 0, 0, winner, 5))
    assert session.answers[-1].show_alert  # the winner can't ask for a rematch

    before = len(session.sent)
    await dp.feed_update(bot, _tap(result.reply_markup, 0, 0, loser, 6))
    assert len(session.sent) == before + 1  # a fresh challenge, despite the 6-hour duel limit
    rematch = await store.pool.fetchrow("SELECT challenger_id, target_id, stake, rematch_of FROM duels WHERE rematch_of IS NOT NULL")
    assert (rematch["challenger_id"], rematch["target_id"], rematch["stake"]) == (loser.id, winner.id, 10)

    # The rematch can be accepted although both just dueled.
    await dp.feed_update(bot, _press(session.sent[-1], 0, winner, 7))
    assert await store.pool.fetchval("SELECT count(*) FROM duels WHERE status = 'accepted'") == 2

    # One rematch per duel.
    await dp.feed_update(bot, _tap(result.reply_markup, 0, 0, loser, 8))
    assert session.answers[-1].show_alert


async def test_all_lists_every_bot_you_play(harness):
    await _send(harness, "/play", update_id=1)
    out = await _send(harness, "/all", update_id=2)
    assert "همه‌ی ربات‌های این گروه" in out and "پشمالویی" in out


async def test_all_before_playing(harness):
    assert "هنوز با هیچ" in await _send(harness, "/all", update_id=1)
