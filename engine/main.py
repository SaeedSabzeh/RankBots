"""Run the bots locally with long polling.

    python -m engine.main            # every theme that has a BOT_TOKEN_<NAME> set
    python -m engine.main --bot cat  # just one

On Render the same bots run behind webhooks instead (engine/web.py); the router and
middleware are shared. Starting this runner deletes any webhook, so stop the Render service
(or re-run scripts/set_webhooks.py afterwards) when you switch back.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from engine.champion import champion_loop
from engine.db import Store
from engine.handlers import build_dispatcher, set_commands
from engine.theme import Theme, load_themes

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader: KEY=value lines; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def bots_to_run(themes: dict[str, Theme], only: list[str] | None) -> list[tuple[Theme, str]]:
    if only:
        unknown = set(only) - themes.keys()
        if unknown:
            raise SystemExit(f"Unknown bot(s): {', '.join(sorted(unknown))}. Themes: {', '.join(themes)}")
    selected = []
    for name, theme in themes.items():
        if only and name not in only:
            continue
        token = os.environ.get(theme.token_env, "").strip()
        if token:
            selected.append((theme, token))
        elif only:
            raise SystemExit(f"{theme.token_env} is not set")
    if not selected:
        raise SystemExit("No bot tokens set. Add BOT_TOKEN_<NAME> to .env (see .env.example).")
    return selected


def new_bot(token: str) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def connect_store() -> Store:
    """Connect to DATABASE_URL and apply the migrations."""
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set (see .env.example)")
    store = await Store.connect(dsn)
    await store.migrate()
    return store


async def run(only: list[str] | None) -> None:
    load_dotenv()
    themes = load_themes()
    selected = bots_to_run(themes, only)
    store = await connect_store()

    bots = [new_bot(token) for _, token in selected]
    by_id = {bot.id: theme for bot, (theme, _) in zip(bots, selected)}

    dp = build_dispatcher(store, by_id)

    for bot, (theme, _) in zip(bots, selected):
        me = await bot.get_me()
        await set_commands(bot, theme)
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Running %s as @%s", theme.name, me.username)

    # Sunday-evening weekly champion posts, alongside the bots.
    champions = asyncio.create_task(champion_loop([(bot, theme) for bot, (theme, _) in zip(bots, selected)], store))
    try:
        await dp.start_polling(*bots)
    finally:
        champions.cancel()
        await store.close()
        for bot in bots:
            await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bot", action="append", help="theme name to run (repeatable); default: all with tokens")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run(args.bot))


if __name__ == "__main__":
    main()
