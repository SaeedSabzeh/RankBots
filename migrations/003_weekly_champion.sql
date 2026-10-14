-- The day each group's weekly champion was last posted, so it's posted once per week
-- even if the in-process scheduler and the Render cron job both run.
ALTER TABLE chats ADD COLUMN IF NOT EXISTS champion_posted_on date;
