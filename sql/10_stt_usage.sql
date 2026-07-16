-- VinoSage 2.0 / Phase 4: voice-transcription spend, folded into the daily
-- cost cap. Closes the step-4 known gap (STT was billed per audio second
-- but invisible to DAILY_COST_CAP_EUR because token_usage is query-keyed
-- and no query exists at transcription time). Convention notes: money in
-- integer micro-euros; OpenRouter reports usage.cost in USD — stored here
-- 1:1 as EUR-equivalent micros, consistent with the illustrative-EUR
-- pricing already used in config.CHAT_MODELS. Service-role only.
create table if not exists stt_usage (
  id              uuid primary key default gen_random_uuid(),
  created_at      timestamptz not null default now(),
  session_id      text not null,
  user_id         uuid references auth.users(id) on delete set null,
  model           text not null,
  seconds         numeric,
  cost_eur_micros integer not null default 0 check (cost_eur_micros >= 0)
);
create index if not exists idx_stt_usage_time on stt_usage(created_at desc);

alter table stt_usage enable row level security;
create policy stt_service on stt_usage
  for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role');
