"""Post the weekly champion to every group, for every bot. For a Render cron job.

    python scripts/weekly_champion.py

Schedule it for Sunday 20:00 Europe/Rome (18:00 or 19:00 UTC depending on summer time;
running it every Sunday at 18:05 and 19:05 UTC is safe, because each group is only posted
once per day). The polling runner posts on its own, so this is only needed on Render.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.champion import post_champions  # noqa: E402
from engine.main import bots_to_run, connect_store, load_dotenv, new_bot  # noqa: E402
from engine.theme import load_themes  # noqa: E402


async def main() -> None:
    load_dotenv()
    store = await connect_store()
    now = datetime.now(timezone.utc)
    try:
        for theme, token in bots_to_run(load_themes(), None):
            bot = new_bot(token)
            try:
                n = await post_champions(bot, theme, store, now)
                logging.info("%s: posted %d weekly champion message(s)", theme.name, n)
            finally:
                await bot.session.close()
    finally:
        await store.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
