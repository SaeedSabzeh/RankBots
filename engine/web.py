"""Run every bot behind Telegram webhooks in one web app (the Render service).

    uvicorn engine.web:app --host 0.0.0.0 --port 8000

Telegram posts each bot's updates to /tg/<bot> with the header
X-Telegram-Bot-Api-Secret-Token, which must match that bot's secret. The secret is an
HMAC of the bot token keyed with WEBHOOK_SECRET, so one env var covers every bot.
scripts/set_webhooks.py registers the URLs and secrets with Telegram.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from fastapi import FastAPI, Header, HTTPException, Request, Response

from engine.handlers import build_dispatcher
from engine.main import bots_to_run, connect_store, load_dotenv, new_bot
from engine.theme import load_themes

log = logging.getLogger(__name__)


def webhook_secret(token: str, key: str) -> str:
    """The secret Telegram sends back for this bot: 64 hex characters, allowed by the Bot API."""
    return hmac.new(key.encode(), token.encode(), hashlib.sha256).hexdigest()


def webhook_key() -> str:
    key = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not key:
        raise SystemExit("WEBHOOK_SECRET is not set (see .env.example)")
    return key


@dataclass
class Webhooks:
    dp: Dispatcher
    bots: dict[str, Bot]  # theme name -> bot
    secrets: dict[str, str]  # theme name -> secret


@asynccontextmanager
async def _from_env() -> AsyncIterator[Webhooks]:
    load_dotenv()
    key = webhook_key()
    selected = bots_to_run(load_themes(), None)
    store = await connect_store()
    bots = {theme.name: new_bot(token) for theme, token in selected}
    dp = build_dispatcher(store, {bots[theme.name].id: theme for theme, _ in selected})
    log.info("Serving webhooks for %s", ", ".join(bots))
    try:
        yield Webhooks(dp, bots, {theme.name: webhook_secret(token, key) for theme, token in selected})
    finally:
        await store.close()
        for bot in bots.values():
            await bot.session.close()


def create_app(hooks: Webhooks | None = None) -> FastAPI:
    """With no `hooks`, the bots are set up from the environment when the app starts."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.hooks is not None:
            yield
            return
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        async with _from_env() as app.state.hooks:
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.hooks = hooks

    @app.api_route("/health", methods=["GET", "HEAD"])
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/tg/{name}")
    async def telegram(
        name: str,
        request: Request,
        secret: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
    ) -> Response:
        hooks: Webhooks = request.app.state.hooks
        bot = hooks.bots.get(name)
        if bot is None:
            raise HTTPException(404)
        if not secret or not hmac.compare_digest(secret, hooks.secrets[name]):
            raise HTTPException(401)
        try:
            await hooks.dp.feed_raw_update(bot, await request.json())
        except Exception:
            # Answer 200 anyway: an error status makes Telegram resend the same update.
            log.exception("Update for %s failed", name)
        return Response()

    return app


app = create_app()
