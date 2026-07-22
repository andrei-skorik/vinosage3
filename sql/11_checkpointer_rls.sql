-- VinoSage 2.0: close a Supabase Security Advisor finding ("RLS Disabled in
-- Public") on the LangGraph checkpointer tables. These tables are created
-- by langgraph-checkpoint-postgres' PostgresSaver.setup() via
-- scripts/setup_checkpointer.py, NOT by this project's own schema — hence
-- no CREATE TABLE here, only a security policy layered on top.
--
-- Why this matters: with RLS disabled, these public-schema tables are
-- reachable, unrestricted, through Supabase's auto-generated PostgREST API
-- by anyone holding the anon key. They hold every logged-in user's full
-- serialized conversation state (SPEC step 9) — a real exposure, not
-- cosmetic.
--
-- Why this is safe to apply: the app's own access to these tables is via
-- DATABASE_URL (a direct psycopg connection, src/checkpointer.py), which
-- authenticates as a role that bypasses RLS by default on Supabase (the
-- "postgres" / pooler role). This policy only closes the PostgREST/anon-key
-- surface — it does not affect the checkpointer's own functionality.
--
-- Apply AFTER scripts/setup_checkpointer.py has created these tables at
-- least once (they must already exist). Idempotent — safe to re-run.

alter table if exists checkpoints           enable row level security;
alter table if exists checkpoint_blobs      enable row level security;
alter table if exists checkpoint_writes     enable row level security;
alter table if exists checkpoint_migrations enable row level security;

drop policy if exists checkpoints_service on checkpoints;
create policy checkpoints_service on checkpoints
  for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');

drop policy if exists checkpoint_blobs_service on checkpoint_blobs;
create policy checkpoint_blobs_service on checkpoint_blobs
  for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');

drop policy if exists checkpoint_writes_service on checkpoint_writes;
create policy checkpoint_writes_service on checkpoint_writes
  for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');

drop policy if exists checkpoint_migrations_service on checkpoint_migrations;
create policy checkpoint_migrations_service on checkpoint_migrations
  for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
