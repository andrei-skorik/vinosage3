-- VinoSage: let a logged-in user read their own past queries, for the
-- "My conversations" history view in the sidebar.
--
-- query_logs currently has service_role-only access (see 02_rls.sql,
-- policy ql_service) — this adds a second policy on top of it so a
-- regular authenticated user can SELECT (never INSERT/UPDATE/DELETE) rows
-- where user_id matches their own auth.uid(). Anonymous sessions (user_id
-- IS NULL) remain invisible to everyone except service_role, as before.
create policy ql_own_read on query_logs
  for select using (auth.uid() = user_id);
