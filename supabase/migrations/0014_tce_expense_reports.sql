create table if not exists licita_ai.tce_municipality_map (
  ibge_code text primary key check (char_length(ibge_code) = 7),
  tce_code text not null check (char_length(tce_code) between 1 and 8),
  municipality_name text not null,
  updated_at timestamptz not null default now()
);

create table if not exists licita_ai.tce_supplier_profiles (
  cnpj text primary key check (char_length(cnpj) = 14),
  company_name text,
  porte_raw text,
  porte_group text not null check (porte_group in ('micro', 'pequena', 'demais', 'desconhecido')),
  source text not null default 'open_cnpj',
  fetched_at timestamptz not null default now()
);

create table if not exists licita_ai.tce_expense_municipality_year (
  municipality_ibge_code text not null check (char_length(municipality_ibge_code) = 7),
  year integer not null check (year >= 2000 and year <= 2100),
  municipality_name text not null,
  total_amount numeric(18,2) not null default 0,
  micro_amount numeric(18,2) not null default 0,
  pequena_amount numeric(18,2) not null default 0,
  demais_amount numeric(18,2) not null default 0,
  unknown_amount numeric(18,2) not null default 0,
  mpe_amount numeric(18,2) not null default 0,
  mpe_percent numeric(8,5),
  matched_liquidations integer not null default 0,
  unmatched_liquidations integer not null default 0,
  source_label text not null default 'Portal da Transparência dos Municípios, TCE.CE.GOV.BR',
  content_hash text not null,
  updated_at timestamptz not null default now(),
  primary key (municipality_ibge_code, year)
);

create table if not exists licita_ai.tce_expense_nature_year (
  municipality_ibge_code text not null check (char_length(municipality_ibge_code) = 7),
  year integer not null check (year >= 2000 and year <= 2100),
  nature_code text not null,
  nature_name text not null,
  total_amount numeric(18,2) not null default 0,
  micro_amount numeric(18,2) not null default 0,
  pequena_amount numeric(18,2) not null default 0,
  demais_amount numeric(18,2) not null default 0,
  unknown_amount numeric(18,2) not null default 0,
  mpe_amount numeric(18,2) not null default 0,
  mpe_percent numeric(8,5),
  content_hash text not null,
  updated_at timestamptz not null default now(),
  primary key (municipality_ibge_code, year, nature_code)
);

create table if not exists licita_ai.tce_sync_requests (
  municipality_ibge_code text not null check (char_length(municipality_ibge_code) = 7),
  year integer not null check (year >= 2000 and year <= 2100),
  status text not null default 'pending' check (status in ('pending', 'running', 'complete', 'failed')),
  attempts smallint not null default 0 check (attempts >= 0),
  next_attempt_at timestamptz not null default now(),
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (municipality_ibge_code, year)
);

create index if not exists tce_sync_requests_pending_idx
  on licita_ai.tce_sync_requests (status, next_attempt_at, updated_at);

alter table licita_ai.tce_municipality_map enable row level security;
alter table licita_ai.tce_supplier_profiles enable row level security;
alter table licita_ai.tce_expense_municipality_year enable row level security;
alter table licita_ai.tce_expense_nature_year enable row level security;
alter table licita_ai.tce_sync_requests enable row level security;

revoke all on
  licita_ai.tce_municipality_map,
  licita_ai.tce_supplier_profiles,
  licita_ai.tce_expense_municipality_year,
  licita_ai.tce_expense_nature_year,
  licita_ai.tce_sync_requests
from anon, authenticated;

grant all on
  licita_ai.tce_municipality_map,
  licita_ai.tce_supplier_profiles,
  licita_ai.tce_expense_municipality_year,
  licita_ai.tce_expense_nature_year,
  licita_ai.tce_sync_requests
to service_role;

create or replace function licita_ai.claim_tce_sync_requests(batch_size integer)
returns setof licita_ai.tce_sync_requests
language sql
set search_path = pg_catalog, licita_ai
as $$
  with selected as (
    select municipality_ibge_code, year
    from licita_ai.tce_sync_requests
    where (
      status = 'pending'
      or (status = 'failed' and next_attempt_at <= now() and attempts < 5)
      or (status = 'running' and updated_at < now() - interval '20 minutes')
    )
    order by next_attempt_at, updated_at
    limit greatest(1, least(batch_size, 10))
    for update skip locked
  )
  update licita_ai.tce_sync_requests queue
  set status = 'running', updated_at = now()
  from selected
  where queue.municipality_ibge_code = selected.municipality_ibge_code
    and queue.year = selected.year
  returning queue.*;
$$;

grant execute on function licita_ai.claim_tce_sync_requests(integer) to service_role;
