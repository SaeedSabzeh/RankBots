# Group Ranking Bots

A family of "grow your X" Telegram group bots on one shared engine. Members `/play`
once per cooldown, get a random score change, and compete on a per-group leaderboard.
Each bot is a Telegram token plus a theme file in `themes/`.

**Status:** Phases 1–3 of the plan: the play loop, leaderboard, rare events, titles, duels
and the theme hook. The cat bot is ready to run locally. Webhooks/Render and the other
seven themes come next.

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
| `engine/main.py` | Long-polling runner |
| `themes/*.yaml` | One file per bot |
| `migrations/*.sql` | Database schema (idempotent) |

## Rules (starting values, in `engine/game.py`)

- Cooldown 12 hours per user per group. Base roll −5 to +10. Score never goes below the theme's `min`.
- Streak: +1 for each consecutive calendar day (Europe/Rome), reset after a missed day.
  Bonus +1 per 3 streak days, capped at +5.
- Rare events: 5% of rolls, replacing the base roll with ±20 to ±50 and the theme's event message.
- Theme hook (optional, one per theme): `kind: lost_turn` with a `chance` and `messages`. When it
  fires the turn is lost: the cooldown is used and the streak counts the day, but the score
  doesn't move. The taarof bot will use it at 10% (see the example at the end of `themes/cat.yaml`).

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
