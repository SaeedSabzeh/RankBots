-- Wakes the Render service when a private reminder is due (see engine/reminders.py).
-- Render's free plan sleeps after 15 idle minutes, so the service's own 30-second loop can't
-- be trusted to run. Every minute this job checks for due reminders and, only if there are
-- any, calls /tick: that wakes the service, which then sends them. Nothing due, no request.
--
-- Run once in the Supabase SQL editor (not a startup migration: the test Postgres has no
-- pg_cron). Re-running replaces the job.
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

SELECT cron.schedule(
    'rank-bots-reminders',
    '* * * * *',
    $$
    SELECT net.http_get('https://rank-bots.onrender.com/tick', timeout_milliseconds := 60000)
    WHERE EXISTS (SELECT 1 FROM public.players WHERE remind AND remind_at <= now())
    $$
);
