-- VinoSage: Row Level Security
alter table wines          enable row level security;
alter table catalog_audit  enable row level security;
alter table query_logs     enable row level security;
alter table tool_call_logs enable row level security;
alter table token_usage    enable row level security;
alter table rate_limit     enable row level security;

-- wines: anonymous users can read active rows; only service_role may write
create policy wines_public_read on wines
  for select using (is_active = true);

create policy wines_service on wines
  for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

-- all log/audit tables: service_role only
create policy audit_service on catalog_audit
  for all using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

create policy ql_service on query_logs
  for all using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

create policy tcl_service on tool_call_logs
  for all using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

create policy tu_service on token_usage
  for all using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

create policy rl_service on rate_limit
  for all using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');
