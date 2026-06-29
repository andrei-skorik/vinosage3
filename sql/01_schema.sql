-- VinoSage: schema
create extension if not exists vector;
create extension if not exists moddatetime;
create extension if not exists pgcrypto;

-- Catalog (editable source of truth) -----------------------------------------
create table if not exists wines (
  wine_id          uuid primary key default gen_random_uuid(),
  source_key       text unique not null,
  title            text not null,
  description      text,
  price_eur_cents  integer,
  capacity_ml      integer default 750,
  grape            text,
  secondary_grapes text,
  closure          text,
  country          text,
  characteristics  text,
  price_unit       text,
  type             text check (type in ('Red','White','Rosé','Tawny','Orange','Brown','Mixed')),
  abv_percent      real,
  region           text,
  style            text,
  vintage_year     integer,
  is_nv            boolean not null default false,
  appellation      text,
  is_active        boolean not null default true,
  content_hash     text,
  needs_embedding  boolean not null default true,
  embedding        vector(1536),
  embedded_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index if not exists idx_wines_active    on wines(is_active);
create index if not exists idx_wines_type      on wines(type)             where is_active;
create index if not exists idx_wines_country   on wines(country)          where is_active;
create index if not exists idx_wines_price     on wines(price_eur_cents)  where is_active;
create index if not exists idx_wines_pending   on wines(needs_embedding)  where needs_embedding;
create index if not exists idx_wines_embedding on wines using hnsw (embedding vector_cosine_ops);

create trigger wines_moddatetime before update on wines
  for each row execute function moddatetime(updated_at);

-- Append-only change log ------------------------------------------------------
create table if not exists catalog_audit (
  id         uuid primary key default gen_random_uuid(),
  wine_id    uuid,
  action     text not null check (action in ('insert','update','delete')),
  actor      text not null default 'app:admin',
  diff       jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_audit_wine on catalog_audit(wine_id);

-- Observability ---------------------------------------------------------------
create table if not exists query_logs (
  id               uuid primary key default gen_random_uuid(),
  session_id       text not null,
  locale           text not null default 'en',
  user_query       text not null,
  rewritten_queries jsonb,
  retrieved_ids    jsonb,
  final_answer     text,
  model            text not null,
  latency_ms       integer,
  status           text not null default 'ok'
    check (status in ('ok','error','rate_limited','refused')),
  error_code       text,
  created_at       timestamptz not null default now()
);
create index if not exists idx_query_logs_session on query_logs(session_id);
create index if not exists idx_query_logs_created on query_logs(created_at desc);

create table if not exists tool_call_logs (
  id         uuid primary key default gen_random_uuid(),
  query_id   uuid not null references query_logs(id) on delete cascade,
  tool_name  text not null check (tool_name in
    ('filter_wines','pair_with_food','calculate_budget','compare_wines','wine_stats')),
  arguments  jsonb not null,
  result     jsonb,
  success    boolean not null default true,
  latency_ms integer,
  created_at timestamptz not null default now()
);
create index if not exists idx_tool_logs_query on tool_call_logs(query_id);

create table if not exists token_usage (
  query_id        uuid primary key references query_logs(id) on delete cascade,
  input_tokens    integer not null default 0,
  output_tokens   integer not null default 0,
  cost_eur_micros bigint  not null default 0
);

create table if not exists rate_limit (
  session_id    text not null,
  window_start  text not null,
  request_count integer not null default 0,
  primary key (session_id, window_start)
);
