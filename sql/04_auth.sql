-- VinoSage: user authentication (Supabase Auth) + simple personalisation

-- Per-user profile data. auth.users itself (email/password/session) is fully
-- managed by Supabase Auth — this table only holds app-specific fields.
create table if not exists user_profiles (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  is_adult   boolean not null default false,
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger user_profiles_moddatetime before update on user_profiles
  for each row execute function moddatetime(updated_at);

alter table user_profiles enable row level security;

-- Each user may only read/insert/update their own profile row.
create policy profiles_own_read on user_profiles
  for select using (auth.uid() = user_id);

create policy profiles_own_insert on user_profiles
  for insert with check (auth.uid() = user_id);

create policy profiles_own_update on user_profiles
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- service_role retains full access (consistent with every other table).
create policy profiles_service on user_profiles
  for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');

-- Link queries to a logged-in user when available (nullable — anonymous
-- sessions still log against session_id only, as before).
alter table query_logs add column if not exists user_id uuid references auth.users(id);
create index if not exists idx_query_logs_user on query_logs(user_id);

-- ── Avatar storage ─────────────────────────────────────────────────────────
-- One public bucket; files are stored at "<user_id>/<filename>" so a simple
-- foldername check enforces "users can only write inside their own folder."
insert into storage.buckets (id, name, public)
values ('avatars', 'avatars', true)
on conflict (id) do nothing;

create policy avatars_public_read on storage.objects
  for select using (bucket_id = 'avatars');

create policy avatars_own_write on storage.objects
  for insert with check (
    bucket_id = 'avatars'
    and auth.uid()::text = (storage.foldername(name))[1]
  );

create policy avatars_own_update on storage.objects
  for update using (
    bucket_id = 'avatars'
    and auth.uid()::text = (storage.foldername(name))[1]
  );

create policy avatars_own_delete on storage.objects
  for delete using (
    bucket_id = 'avatars'
    and auth.uid()::text = (storage.foldername(name))[1]
  );
