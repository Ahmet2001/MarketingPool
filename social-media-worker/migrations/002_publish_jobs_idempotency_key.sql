-- Optional idempotency key so a caller (marketing-agent's
-- worker_video_yayinla / worker_instagram_carousel_yayinla) can retry an
-- insert (network timeout, an LLM re-attempting the same tool call) without
-- creating a duplicate publish job.
--
-- Backward compatible: the column is nullable and the unique index is
-- partial (`where idempotency_key is not null`), so every existing row and
-- every caller that never sets this column keeps working exactly as before.
alter table publish_jobs add column if not exists idempotency_key text;

create unique index if not exists publish_jobs_idempotency_key_uidx
  on publish_jobs (idempotency_key)
  where idempotency_key is not null;

-- ---------------------------------------------------------------------------
-- Least-privilege access for marketing-agent (see agents/marketing-agent's
-- AGENT.md "Supabase anahtarini daraltma" section).
--
-- Today marketing-agent authenticates with SUPABASE_SECRET_KEY (the
-- service-role key), which bypasses RLS entirely and can read/write every
-- table in the project -- far more than it needs. Everything below is a
-- ready-to-run alternative: create a role that can only insert and read
-- publish_jobs, generate an API key for it (Supabase project settings ->
-- API Keys -> "Create a new key" -> pick this role), and put that key in
-- marketing-agent's SUPABASE_AGENT_KEY (worker_yayinlama_araclari.py already
-- prefers it over SUPABASE_SECRET_KEY when both are set).
--
-- This is NOT applied automatically by running this migration -- creating
-- the actual API key tied to this role is a dashboard action only the
-- project owner can do. Uncomment and run the block below once you're ready
-- to provision it; until then nothing changes and the service-role key
-- keeps working as it does today.
--
-- create role marketing_agent_writer nologin;
-- grant usage on schema public to marketing_agent_writer;
-- grant select, insert on publish_jobs to marketing_agent_writer;
--
-- create policy marketing_agent_writer_select on publish_jobs
--   for select to marketing_agent_writer using (true);
-- create policy marketing_agent_writer_insert on publish_jobs
--   for insert to marketing_agent_writer with check (true);
