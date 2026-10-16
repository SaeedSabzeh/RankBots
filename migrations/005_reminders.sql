-- Private "your turn is ready" reminders, opted into per bot and group.
-- remind_at is when the next one is due: set by each /play while `remind` is on, cleared once sent.
ALTER TABLE players ADD COLUMN IF NOT EXISTS remind boolean NOT NULL DEFAULT false;
ALTER TABLE players ADD COLUMN IF NOT EXISTS remind_at timestamptz;
CREATE INDEX IF NOT EXISTS players_remind_due_idx ON players (remind_at) WHERE remind_at IS NOT NULL;
