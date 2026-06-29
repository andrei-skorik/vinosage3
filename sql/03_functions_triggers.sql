-- VinoSage: functions and triggers

-- Flag rows whose embedded text changed so the reconcile job re-embeds them --
create or replace function flag_wine_embedding() returns trigger as $$
declare
  new_hash text;
begin
  new_hash := md5(concat_ws('|',
    coalesce(NEW.title,''),
    coalesce(NEW.type,''),
    coalesce(NEW.grape,''),
    coalesce(NEW.region,''),
    coalesce(NEW.country,''),
    coalesce(NEW.style,''),
    coalesce(NEW.characteristics,''),
    coalesce(NEW.description,'')
  ));
  if TG_OP = 'INSERT' or new_hash is distinct from OLD.content_hash then
    NEW.content_hash    := new_hash;
    NEW.needs_embedding := true;
    NEW.embedding       := null;
  end if;
  return NEW;
end;
$$ language plpgsql;

drop trigger if exists trg_flag_embedding on wines;
create trigger trg_flag_embedding
  before insert or update on wines
  for each row execute function flag_wine_embedding();

-- Append-only audit log -------------------------------------------------------
create or replace function log_wine_change() returns trigger as $$
begin
  if TG_OP = 'DELETE' then
    insert into catalog_audit(wine_id, action, diff)
      values (OLD.wine_id, 'delete', to_jsonb(OLD) - 'embedding');
    return OLD;
  elsif TG_OP = 'INSERT' then
    insert into catalog_audit(wine_id, action, diff)
      values (NEW.wine_id, 'insert', to_jsonb(NEW) - 'embedding');
    return NEW;
  else
    insert into catalog_audit(wine_id, action, diff)
      values (NEW.wine_id, 'update',
              jsonb_build_object(
                'old', to_jsonb(OLD) - 'embedding',
                'new', to_jsonb(NEW) - 'embedding'
              ));
    return NEW;
  end if;
end;
$$ language plpgsql;

drop trigger if exists trg_audit on wines;
create trigger trg_audit
  after insert or update or delete on wines
  for each row execute function log_wine_change();

-- Semantic search with metadata filter (active + embedded rows only) ----------
create or replace function match_wines(
  query_embedding  vector(1536),
  match_count      int     default 8,
  filter           jsonb   default '{}'
) returns table (
  wine_id    uuid,
  title      text,
  similarity float,
  payload    jsonb
)
language sql stable as $$
  select
    w.wine_id,
    w.title,
    1 - (w.embedding <=> query_embedding) as similarity,
    to_jsonb(w) - 'embedding' as payload
  from wines w
  where
    w.is_active
    and w.embedding is not null
    and (filter->>'type'    is null or w.type    =      filter->>'type')
    and (filter->>'country' is null or w.country =      filter->>'country')
    and (filter->>'grape'   is null or w.grape   ilike  filter->>'grape')
    and (filter->>'style'   is null or w.style   =      filter->>'style')
    and (filter->>'max_price_eur' is null
         or w.price_eur_cents <= (filter->>'max_price_eur')::numeric * 100)
  order by w.embedding <=> query_embedding
  limit match_count;
$$;
