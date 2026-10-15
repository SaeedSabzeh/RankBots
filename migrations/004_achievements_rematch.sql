-- Achievements: one row per badge a player has earned, per bot and group.
CREATE TABLE IF NOT EXISTS achievements (
    bot       text        NOT NULL,
    chat_id   bigint      NOT NULL,
    user_id   bigint      NOT NULL,
    code      text        NOT NULL,
    earned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (bot, chat_id, user_id, code)
);
ALTER TABLE achievements ENABLE ROW LEVEL SECURITY;

-- Rematches: a duel can be answered by one rematch, which skips the 6-hour duel limit.
ALTER TABLE duels ADD COLUMN IF NOT EXISTS rematch_of bigint;
CREATE UNIQUE INDEX IF NOT EXISTS duels_one_rematch ON duels (bot, rematch_of) WHERE rematch_of IS NOT NULL;
