"""The webhook app: secrets, routing, and updates reaching the real dispatcher."""

from typing import Any

import httpx
import pytest
from aiogram import Bot
from aiogram.methods import SetMyCommands, SetWebhook, TelegramMethod

from engine.db import Store
from engine.handlers import build_dispatcher
from engine.web import Webhooks, create_app, webhook_secret
from scripts.set_webhooks import register
from test_handlers import CAT, TOKEN, FakeSession, _update

KEY = "test-webhook-key"
SECRET = webhook_secret(TOKEN, KEY)


@pytest.fixture
async def web(pg_uri):
    store = await Store.connect(pg_uri)
    await store.migrate()
    await store.pool.execute("TRUNCATE chats, players, plays, duels")
    session = FakeSession()
    bot = Bot(TOKEN, session=session)
    hooks = Webhooks(build_dispatcher(store, {bot.id: CAT}), {"cat": bot}, {"cat": SECRET})
    transport = httpx.ASGITransport(app=create_app(hooks))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session
    await store.close()


def _body(text: str, update_id: int = 1) -> str:
    return _update(text, update_id=update_id).model_dump_json(by_alias=True, exclude_none=True)


def _headers(secret: str | None = SECRET) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    return headers


async def test_health(web):
    client, _ = web
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


async def test_update_with_the_right_secret_is_handled(web):
    client, session = web
    r = await client.post("/tg/cat", content=_body("/play"), headers=_headers())
    assert r.status_code == 200
    assert len(session.sent) == 1 and "Simin" in session.sent[0].text


@pytest.mark.parametrize("secret", [None, "", "wrong", webhook_secret(TOKEN, "another-key")])
async def test_bad_or_missing_secret_is_rejected(web, secret):
    client, session = web
    r = await client.post("/tg/cat", content=_body("/play"), headers=_headers(secret))
    assert r.status_code == 401
    assert session.sent == []


async def test_unknown_bot_is_404(web):
    client, session = web
    r = await client.post("/tg/konkur", content=_body("/play"), headers=_headers())
    assert r.status_code == 404
    assert session.sent == []


async def test_a_failing_update_still_answers_200(web):
    # Telegram resends anything that isn't a 2xx, so a broken update must not loop forever.
    client, session = web
    r = await client.post("/tg/cat", content='{"update_id": 1, "message": {"oops": 1}}', headers=_headers())
    assert r.status_code == 200 and session.sent == []


def test_secrets_differ_per_bot_and_key():
    assert webhook_secret(TOKEN, KEY) == SECRET
    assert webhook_secret("987654321:BBBB", KEY) != SECRET
    assert webhook_secret(TOKEN, "other") != SECRET
    assert len(SECRET) == 64 and SECRET.isalnum()  # Telegram allows 1-256 of A-Z a-z 0-9 _ -


class RecordingSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, (SetWebhook, SetMyCommands)):
            self.calls.append(method)
            return True
        return await super().make_request(bot, method, timeout)


async def test_register_sets_webhook_and_commands():
    session = RecordingSession()
    bot = Bot(TOKEN, session=session)
    url = await register(bot, CAT, "https://bots.example.com", KEY)
    assert url == "https://bots.example.com/tg/cat"

    hook = next(c for c in session.calls if isinstance(c, SetWebhook))
    assert hook.url == url and hook.secret_token == SECRET
    assert sorted(hook.allowed_updates) == ["callback_query", "message"]
    assert any(isinstance(c, SetMyCommands) for c in session.calls)
