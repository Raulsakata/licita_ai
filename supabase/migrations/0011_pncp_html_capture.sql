alter table licita_ai.pncp_opportunities
  add column if not exists html_data jsonb not null default '{}'::jsonb,
  add column if not exists content_hash text,
  add column if not exists source_url text,
  add column if not exists scraped_at timestamptz;

alter table licita_ai.pncp_open_opportunities
  add column if not exists html_data jsonb not null default '{}'::jsonb,
  add column if not exists content_hash text,
  add column if not exists source_url text,
  add column if not exists scraped_at timestamptz;

create table if not exists licita_ai.pncp_html_scrape_queue (
  pncp_id text primary key,
  page_url text not null,
  source_hash text not null,
  status text not null default 'pending'
    check (status in ('pending', 'running', 'complete', 'failed', 'dead')),
  attempts smallint not null default 0 check (attempts >= 0),
  next_attempt_at timestamptz not null default now(),
  scraped_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists pncp_html_scrape_queue_pending_idx
  on licita_ai.pncp_html_scrape_queue (status, next_attempt_at, created_at);

alter table licita_ai.pncp_html_scrape_queue enable row level security;
revoke all on licita_ai.pncp_html_scrape_queue from anon, authenticated;
grant all on licita_ai.pncp_html_scrape_queue to service_role;

create or replace function licita_ai.claim_pncp_html_scrapes(batch_size integer)
returns setof licita_ai.pncp_html_scrape_queue
language sql
set search_path = pg_catalog, licita_ai
as $$
  with selected as (
    select pncp_id
    from licita_ai.pncp_html_scrape_queue
    where (
      status = 'pending'
      or (status = 'failed' and attempts < 5 and next_attempt_at <= now())
      or (status = 'running' and updated_at < now() - interval '15 minutes')
    )
    order by next_attempt_at, created_at
    limit greatest(1, least(batch_size, 25))
    for update skip locked
  )
  update licita_ai.pncp_html_scrape_queue as queue
  set status = 'running', updated_at = now()
  from selected
  where queue.pncp_id = selected.pncp_id
  returning queue.*;
$$;

grant execute on function licita_ai.claim_pncp_html_scrapes(integer) to service_role;
