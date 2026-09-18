-- platform_data_jobs: the queue between marketing-agent (which asks for
-- platform data) and platform_data_worker (which holds the platform credentials,
-- runs an allowlisted read-only toolbox action, and writes the answer back).
-- Same shape and claim pattern as publish_jobs / agent_jobs; `results` follows
-- schemas/platform_data_result.schema.json, `payload` follows
-- schemas/platform_data_request.schema.json.
create table if not exists platform_data_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_ref text,
  status text not null default 'queued' check (status in ('queued', 'processing', 'done', 'failed')),
  payload jsonb not null,
  results jsonb not null default '{}'::jsonb,
  error text,
  attempts integer not null default 0,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists platform_data_jobs_status_created_idx on platform_data_jobs(status, created_at);
-- The worker counts recent runs per (platform, action) to enforce each action's
-- rate_limit_per_hour from the manifest.
create index if not exists platform_data_jobs_action_created_idx
  on platform_data_jobs ((payload->>'platform'), (payload->>'action'), created_at);
alter table platform_data_jobs enable row level security;

create or replace function claim_platform_data_job()
returns platform_data_jobs
language plpgsql
as $$
declare claimed platform_data_jobs;
begin
  with candidate as (
    select id from platform_data_jobs where status = 'queued'
    order by created_at asc for update skip locked limit 1
  )
  update platform_data_jobs job set
    status = 'processing', attempts = job.attempts + 1,
    started_at = now(), updated_at = now(), error = null
  from candidate where job.id = candidate.id
  returning job.* into claimed;
  return claimed;
end;
$$;

-- ---------------------------------------------------------------------------
-- Least privilege (see agents/marketing-agent/AGENT.md "Supabase anahtarini
-- daraltma"). The agent only ever inserts jobs and reads their results, so the
-- marketing_agent_writer role from the other migrations needs just this. Not
-- applied automatically; uncomment once that role exists.
--
-- grant select, insert on platform_data_jobs to marketing_agent_writer;
-- create policy marketing_agent_writer_select on platform_data_jobs
--   for select to marketing_agent_writer using (true);
-- create policy marketing_agent_writer_insert on platform_data_jobs
--   for insert to marketing_agent_writer with check (true);
