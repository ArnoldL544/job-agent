-- OPTIONAL CLOUD MIGRATION FOR A NEW PRIVATE SUPABASE PROJECT.
-- Do not run against an existing production database without a reviewed migration.
-- Authentication via Supabase Auth Google provider; Gmail API authorization is SEPARATE.

create extension if not exists pgcrypto;

create table if not exists public.career_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  profile jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  constraint profile_json_object check (jsonb_typeof(profile) = 'object')
);

create table if not exists public.job_listings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  external_job_id text not null,
  company text not null default '',
  title text not null default '',
  jd_text text not null default '',
  source_url text,
  screening_score integer check (screening_score between 0 and 100),
  screening_flags jsonb not null default '[]'::jsonb,
  source_metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  unique(user_id, external_job_id),
  unique(id, user_id)
);

create table if not exists public.job_applications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null,
  status text not null default 'Discovered',
  deadline date,
  note text not null default '',
  updated_at timestamptz not null default now(),
  constraint valid_application_status check (status in ('Discovered','Saved','Applied','Interview','Offer','Rejected','Withdrawn')),
  constraint owned_application_job foreign key (job_id, user_id) references public.job_listings(id,user_id) on delete cascade,
  unique(user_id,job_id)
);

create table if not exists public.resume_versions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null,
  version_number integer not null check (version_number > 0),
  storage_path text not null,
  review_status text not null default 'draft' check (review_status in ('draft','reviewed','approved')),
  created_at timestamptz not null default now(),
  constraint owned_resume_job foreign key (job_id,user_id) references public.job_listings(id,user_id) on delete cascade,
  unique(job_id,version_number),
  constraint scoped_storage_path check (storage_path like (user_id::text || '/%'))
);

create table if not exists public.agent_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  action text not null check (action in ('import','extract','screen','resume')),
  job_id uuid,
  status text not null default 'queued' check (status in ('queued','running','succeeded','failed','cancelled')),
  params jsonb not null default '{}'::jsonb,
  progress jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint owned_run_job foreign key (job_id,user_id) references public.job_listings(id,user_id) on delete cascade
);

create table if not exists public.discovery_schedules (
  user_id uuid primary key references auth.users(id) on delete cascade,
  enabled boolean not null default false,
  frequency text not null default 'weekly' check (frequency in ('daily','weekly')),
  weekday integer not null default 0 check (weekday between 0 and 6),
  hour integer not null default 9 check (hour between 0 and 23),
  minute integer not null default 0 check (minute between 0 and 59),
  timezone text not null default 'UTC',
  max_emails integer not null default 20 check (max_emails between 1 and 50),
  updated_at timestamptz not null default now()
);

-- Gmail refresh tokens are never writable or readable by public/anon/authenticated clients.
-- Store only ciphertext encrypted by a separate server-held key (NOT the public anon key).
-- A service-role worker owns consent/revocation/rotation logic; no public RLS policy.
create table if not exists public.gmail_private_connections (
  user_id uuid primary key references auth.users(id) on delete cascade,
  encrypted_refresh_token bytea not null,
  granted_scopes text[] not null default '{}',
  granted_at timestamptz not null default now(),
  revoked_at timestamptz
);

alter table public.career_profiles enable row level security;
alter table public.job_listings enable row level security;
alter table public.job_applications enable row level security;
alter table public.resume_versions enable row level security;
alter table public.agent_runs enable row level security;
alter table public.discovery_schedules enable row level security;
alter table public.gmail_private_connections enable row level security;

-- Tight table grants: no access to private Gmail credentials for browser roles.
revoke all on table public.gmail_private_connections from anon, authenticated;
revoke insert, update, delete on table public.agent_runs from anon, authenticated;

create policy "profile_owner" on public.career_profiles for all to authenticated using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
create policy "jobs_owner" on public.job_listings for all to authenticated using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
create policy "applications_owner" on public.job_applications for all to authenticated using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
create policy "resumes_owner" on public.resume_versions for all to authenticated using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
create policy "runs_owner_read" on public.agent_runs for select to authenticated using ((select auth.uid())=user_id);
create policy "schedule_owner" on public.discovery_schedules for all to authenticated using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);

-- Private versioned Word storage, path prefix MUST be user UUID.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('resume-files','resume-files',false,15728640,array['application/vnd.openxmlformats-officedocument.wordprocessingml.document'])
on conflict (id) do nothing;

create policy "read_own_resume_files" on storage.objects for select to authenticated
using (bucket_id='resume-files' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy "upload_own_resume_files" on storage.objects for insert to authenticated
with check (bucket_id='resume-files' and (storage.foldername(name))[1]=(select auth.uid())::text);
-- Deliberately no UPDATE/DELETE policies for immutable resume versions.

create index if not exists idx_jobs_user_updated on public.job_listings(user_id,updated_at desc);
create index if not exists idx_runs_user_created on public.agent_runs(user_id,created_at desc);
create index if not exists idx_apps_user_deadline on public.job_applications(user_id,deadline);
