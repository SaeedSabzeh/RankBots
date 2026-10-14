-- Cooldowns now come from each theme, in minutes (chai: 5, cat: 90).
-- A group can still get its own value later (admin commands); NULL means "use the theme's".
ALTER TABLE chats ADD COLUMN IF NOT EXISTS cooldown_minutes integer CHECK (cooldown_minutes > 0);
ALTER TABLE chats DROP COLUMN IF EXISTS cooldown_hours;
