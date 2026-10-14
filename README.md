# Group Ranking Bots

A family of "grow your X" Telegram group bots on one shared engine. Members `/play`
once per cooldown, get a random score change, and compete on a per-group leaderboard.
Each bot is a Telegram token plus a theme file in `themes/`.

**Status:** Phases 1–4 of the plan: the play loop, leaderboard, rare events, titles, duels,
the theme hook, and a webhook web service for Render. The other seven themes come next.

## Run the cat bot locally

1. Create the bot with [@BotFather](https://t.me/BotFather) (`/newbot`), then copy the token.
   Leave privacy mode on: commands still reach the bot in groups.
2. Create a Supabase project and copy the **session pooler** connection string
   (Project Settings → Database → Connection string → URI, port 5432).
3. Set up the environment:

   ```bash
   py -3.11 -m venv .venv
   .venv/Scripts/python -m pip install -r requirements-dev.txt
   cp .env.example .env   # then fill in DATABASE_URL and BOT_TOKEN_CAT
   ```

4. Start it. Tables are created on startup from `migrations/`:

   ```bash
   .venv/Scripts/python -m engine.main --bot cat
   ```

5. Add the bot to a private test group and send `/play`, `/me`, `/top`, `/duel @someone 5`.

## Deploy on Render

On Render all bots run in one web service, `engine/web.py` (FastAPI). Telegram posts each
bot's updates to `POST /tg/<bot>` (e.g. `/tg/cat`) and the service checks the
`X-Telegram-Bot-Api-Secret-Token` header before handing the update to the same dispatcher the
long-polling runner uses: wrong or missing secret → 401, unknown bot → 404. `GET /health` is
the health check. Tables are created on startup, as with polling.

Environment variables on the service:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Supabase **session pooler** URI: `postgresql://postgres.<ref>:<password>@aws-1-eu-central-1.pooler.supabase.com:5432/postgres` (port 5432; the transaction pooler on 6543 doesn't work with asyncpg) |
| `WEBHOOK_SECRET` | Any long random string: `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Each bot's webhook secret is an HMAC of its token with this key |
| `BOT_TOKEN_CAT` | The cat bot's token; add `BOT_TOKEN_<NAME>` for each further bot |
| `PYTHON_VERSION` | `3.11.9` (set by `render.yaml`) |

Steps:

1. In Render, **New → Blueprint**, pick this repo; `render.yaml` defines the service
   (`uvicorn engine.web:app`, Frankfurt, health check `/health`). Fill in the three secrets.
   Or create a Python web service by hand with build command `pip install -r requirements.txt`
   and start command `uvicorn engine.web:app --host 0.0.0.0 --port $PORT`.
2. Wait for the deploy, then check `https://<service>.onrender.com/health` returns `{"ok":true}`.
3. Stop any local `engine.main` for the same bots, then register the webhooks. Locally, put
   the same `WEBHOOK_SECRET` and `PUBLIC_URL=https://<service>.onrender.com` in `.env`:

   ```bash
   .venv/Scripts/python scripts/set_webhooks.py
   .venv/Scripts/python scripts/set_webhooks.py --info   # check: URL set, no last_error
   ```

   It also sets each bot's command menu. (In a Render shell, `PUBLIC_URL` can be left out:
   `RENDER_EXTERNAL_URL` is used.)

A bot has either a webhook or long polling, not both. Starting `engine.main` deletes the
bot's webhook, so to go back to Render afterwards, stop it and run `set_webhooks.py` again.
On Render's free plan the service sleeps after 15 idle minutes: Telegram's retries wake it,
but the first reply after a quiet spell takes about a minute. `render.yaml` uses Starter.

## Tests

```bash
.venv/Scripts/python -m pytest
```

The database and handler tests start a throwaway local Postgres with `pgserver`, so
they don't need Supabase or a real bot token.

## Layout

| Path | What it is |
| --- | --- |
| `engine/theme.py` | Theme schema and loader; every YAML file is validated at startup |
| `engine/game.py` | Pure rules: roll, streak, bonus, events, titles, cooldown |
| `engine/db.py` | Postgres queries; the cooldown check and score update are one `UPDATE` |
| `engine/service.py` | The `/play`, `/me`, `/top` and `/duel` flows |
| `engine/texts.py` | Every message, in Farsi and English |
| `engine/handlers.py` | aiogram handlers; one dispatcher serves every bot |
| `engine/main.py` | Long-polling runner (local); also runs the weekly champion scheduler |
| `engine/champion.py` | The Sunday weekly champion post |
| `engine/web.py` | Webhook web service (Render): `POST /tg/<bot>`, `GET /health` |
| `scripts/set_webhooks.py` | Registers every bot's webhook and command menu with Telegram |
| `scripts/weekly_champion.py` | Posts the weekly champion once; for a Render cron job |
| `render.yaml` | Render Blueprint for the web service |
| `themes/*.yaml` | One file per bot |
| `migrations/*.sql` | Database schema (idempotent) |

## Rules (starting values, in `engine/game.py`)

- Cooldown per user per group, set by each theme's `cooldown_minutes` to match the joke: chai 5 min,
  taarof 15, mom 30, tahdig 60, cat 90, khastegari 180 (default 12 hours). A group's own
  `chats.cooldown_minutes` overrides it. Base roll −5 to +10. Score never goes below the theme's `min`.
- Streak: +1 for each consecutive calendar day (Europe/Rome), reset after a missed day.
  Bonus +1 per 3 streak days, capped at +5.
- Rare events: 5% of rolls, replacing the base roll with ±20 to ±50 and the theme's event message.
- Theme hook (optional, one per theme): `kind: lost_turn` with a `chance` and `messages`. When it
  fires the turn is lost: the cooldown is used and the streak counts the day, but the score
  doesn't move. The taarof bot will use it at 10% (see the example at the end of `themes/cat.yaml`).

## Surprises

All in `engine/game.py` (boosts, Persian calendar) and `engine/champion.py`. Active boosts show as a
banner line at the top of the `/play` reply, and they stack (Yalda in the lucky hour = gains ×4).

- **🍀 Lucky hour:** every day each bot has one secret hour between 9:00 and 22:59 (Rome) when
  gains are doubled. It's a hash of the bot and the date, so it's the same for every group and
  different for every bot and day. Losses are never doubled.
- **Persian holidays,** from the Jalali calendar (the jalaali-js algorithm, checked against
  known Nowruz dates):
  - 🔥 Chaharshanbe Suri (the Tuesday before the last Wednesday of Esfand): rare events at 20%.
  - 🌸 Nowruz (1–12 Farvardin): rare events at 15%.
  - 🌿 Sizdah Bedar (13 Farvardin): no losses; bad rolls turn into gains and no bad events.
  - 🍉 Shab-e Yalda (30 Azar): gains doubled.
- **🏆 Weekly champion:** every Sunday from 20:00 (Rome), each group that played that week gets
  a post with the week's top three movers (sum of `plays.delta` in the good direction over 7
  days, rolls and duels) and the overall leader. The polling runner checks every 5 minutes. On
  Render, run `python scripts/weekly_champion.py` as a cron job on Sundays at 18:05 and 19:05 UTC
  (covers summer and winter time). `chats.champion_posted_on` makes sure a group is posted once.

## Duels

- `/duel @user <stake>`, or reply to someone's message with `/duel <stake>`. A mention of a
  user without a username works too. `@user` is looked up among this group's players, so the
  target must have played here already (the Bot API can't resolve usernames).
- Only the target can press Accept or Decline. Challenges expire after 10 minutes. There is no
  timer: an old challenge simply stops counting, and its message changes to "expired" when
  someone presses one of its buttons.
- One duel per user every 6 hours (`players.last_duel_at`), counted for both players and only
  when a duel is actually fought; a declined or expired challenge costs nothing. A challenger can
  have one open challenge at a time. Duels don't touch the `/play` cooldown.
- 50/50 outcome; the winner takes the stake. Both moves are logged in `plays` as `event = 'duel'`.
- Accepting is one transaction: `UPDATE duels ... WHERE status = 'pending' RETURNING` claims the
  duel, both player rows are locked and re-checked (stake, 6-hour limit), then both scores move.
  If a check fails, everything rolls back and the duel stays open.

**Stakes in either direction.** A stake is typed in the score's own units (no `scale`), and a
player can stake at most their distance to the theme's floor, `score − min`. Higher is better:
that is just "you must have the points", since the loser moves toward the floor. Lower is better
(konkur, `min: 1`): winning lowers your rank by the stake and losing raises it, so the winner is
the one moving toward the floor, and `score − min` is how far you can still improve. Rank 10 can
stake at most 9. Checking it for both players means every duel is exactly zero-sum, never clipped
by the floor.

## Adding a bot

1. Copy `themes/cat.yaml` to `themes/<name>.yaml` and rewrite the copy. `language` is
   `fa`, `en` or `both`; every text needs each language it uses.
2. Set `BOT_TOKEN_<NAME>` in `.env`.
3. Run `python -m pytest` (it validates every theme), then `python -m engine.main --bot <name>`.
4. To go live, add `BOT_TOKEN_<NAME>` on Render (and to `render.yaml`), let it redeploy, then
   run `python scripts/set_webhooks.py --bot <name>`.

## Profile pictures

`assets/avatars/` has one avatar per bot (preview: `assets/avatars/preview.png`), drawn as
SVG by `scripts/make_avatars.py`. The 640px PNGs in `assets/avatars/png/` are ready for
BotFather: send `/setuserpic`, pick the bot, then send the PNG **as a photo** (not as a file).
Telegram crops avatars to a circle; every drawing stays inside it.
