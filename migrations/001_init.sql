-- Group Ranking Bots: shared tables for every themed bot.
-- The `bot` column (e.g. 'cat', 'konkur') keeps each bot's data apart.

CREATE TABLE IF NOT EXISTS chats (
    bot            text        NOT NULL,
    chat_id        bigint      NOT NULL,
    title          text,
    cooldown_hours integer     NOT NULL DEFAULT 12 CHECK (cooldown_hours > 0),
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (bot, chat_id)
);

CREATE TABLE IF NOT EXISTS players (
    bot            text        NOT NULL,
    chat_id        bigint      NOT NULL,
    user_id        bigint      NOT NULL,
    username       text,
    first_name     text,
    score          bigint      NOT NULL,
    streak         integer     NOT NULL DEFAULT 0,
    last_play_at   timestamptz,
    last_play_date date,
    last_duel_at   timestamptz,
    PRIMARY KEY (bot, chat_id, user_id),
    FOREIGN KEY (bot, chat_id) REFERENCES chats (bot, chat_id) ON DELETE CASCADE
);

-- Leaderboard reads: rank players of one chat by score.
CREATE INDEX IF NOT EXISTS players_leaderboard_idx ON players (bot, chat_id, score);

CREATE TABLE IF NOT EXISTS plays (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bot         text        NOT NULL,
    chat_id     bigint      NOT NULL,
    user_id     bigint      NOT NULL,
    delta       bigint      NOT NULL,
    event       text,
    score_after bigint      NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS plays_chat_time_idx ON plays (bot, chat_id, created_at);

CREATE TABLE IF NOT EXISTS duels (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bot           text        NOT NULL,
    chat_id       bigint      NOT NULL,
    challenger_id bigint      NOT NULL,
    target_id     bigint      NOT NULL,
    stake         bigint      NOT NULL CHECK (stake > 0),
    status        text        NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'accepted', 'declined', 'expired')),
    winner_id     bigint,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Only the service role talks to these tables; keep the Supabase REST API out.
ALTER TABLE chats   ENABLE ROW LEVEL SECURITY;
ALTER TABLE players ENABLE ROW LEVEL SECURITY;
ALTER TABLE plays   ENABLE ROW LEVEL SECURITY;
ALTER TABLE duels   ENABLE ROW LEVEL SECURITY;
