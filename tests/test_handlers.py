"""Feed fake Telegram updates through the real dispatcher and capture the replies."""

import re
from datetime import datetime, timezone
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, EditMessageText, GetMe, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User

from engine.db import Store
from engine.handlers import build_dispatcher
from engine.theme import load_themes

CAT = load_themes()["cat"]
TOKEN = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
BOT_USER = User(id=123456789, is_bot=True, first_name="Cat", username="CatTestBot")


class FakeSession(BaseSession):
    """Answers Bot API calls locally and remembers every message the bot sent."""

    def __init__(self):
        super().__init__()
        self.sent: list[SendMessage] = []
        self.edits: list[EditMessageText] = []
        self.answers: list[AnswerCallbackQuery] = []

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
    assert session.edits[0].reply_markup is None
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
    assert "عدد صحیح" in await _send(harness, "/duel @arash", user=SIMIN, update_id=3)
    assert "عدد صحیح" in await _send(harness, "/duel 20", user=SIMIN, update_id=4)  # nobody to duel
    assert "عدد صحیح" in await _send(harness, "/duel @arash 0", user=SIMIN, update_id=5)
    assert "حداکثر" in await _send(harness, "/duel @arash 20", user=SIMIN, update_id=6)
    assert "نمی‌شناسم" in await _send(harness, "/duel @ghost 1", user=SIMIN, update_id=7)
    assert "ربات" in await _send(harness, "/duel 1", user=SIMIN, reply_to=BOT_USER, update_id=8)
    assert "خودت" in await _send(harness, "/duel @simin 1", user=SIMIN, update_id=9)
    assert "گروه" in await _send(harness, "/duel @arash 1", chat_type="private", update_id=10)
