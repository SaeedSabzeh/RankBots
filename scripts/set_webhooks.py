"""Point each bot's Telegram webhook at the web service and set its command menu.

    python scripts/set_webhooks.py            # every theme that has a BOT_TOKEN_<NAME> set
    python scripts/set_webhooks.py --bot cat  # just one
    python scripts/set_webhooks.py --info     # show what Telegram has now, change nothing

Needs PUBLIC_URL (the service's https URL; on Render, RENDER_EXTERNAL_URL is used if it's
unset) and the same WEBHOOK_SECRET the service runs with. Once a webhook is set, long
polling (engine.main) stops getting updates for that bot until it deletes the webhook.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot  # noqa: E402

from engine.handlers import build_dispatcher, set_commands  # noqa: E402
from engine.main import bots_to_run, load_dotenv, new_bot  # noqa: E402
from engine.theme import Theme, load_themes  # noqa: E402
from engine.web import webhook_key, webhook_secret  # noqa: E402

# The update types the handlers use (message, callback_query); Telegram skips the rest.
ALLOWED_UPDATES = build_dispatcher(None, {}).resolve_used_update_types()


def public_url() -> str:
    url = (os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if not url.startswith("https://"):
        raise SystemExit("PUBLIC_URL must be the service's https:// URL, e.g. https://rank-bots.onrender.com")
    return url


async def register(bot: Bot, theme: Theme, base_url: str, key: str) -> str:
    url = f"{base_url}/tg/{theme.name}"
    await bot.set_webhook(url, secret_token=webhook_secret(bot.token, key), allowed_updates=ALLOWED_UPDATES)
    await set_commands(bot, theme)
    return url


async def run(only: list[str] | None, info: bool) -> None:
    load_dotenv()
    selected = bots_to_run(load_themes(), only)
    if not info:
        base_url, key = public_url(), webhook_key()
    for theme, token in selected:
        bot = new_bot(token)
        try:
            if info:
                wh = await bot.get_webhook_info()
                print(f"{theme.name}: {wh.url or '(no webhook, long polling)'} pending={wh.pending_update_count}"
                      + (f" last_error={wh.last_error_message!r}" if wh.last_error_message else ""))
            else:
                print(f"{theme.name}: webhook set to {await register(bot, theme, base_url, key)}")
        finally:
            await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bot", action="append", help="theme name (repeatable); default: all with tokens")
    parser.add_argument("--info", action="store_true", help="print the current webhook of each bot")
    args = parser.parse_args()
    asyncio.run(run(args.bot, args.info))


if __name__ == "__main__":
    main()
