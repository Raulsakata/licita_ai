create table if not exists licita_ai.pncp_open_opportunities (
  pncp_id text primary key,
  municipality_ibge_code text check (municipality_ibge_code is null or char_length(municipality_ibge_code) = 7),
  uf text not null default 'CE' check (uf = 'CE'),
  proposal_end timestamptz,
  raw_data jsonb not null,
  updated_at timestamptz not null default now()
);
create index if not exists pncp_open_opportunities_city_idx
  on licita_ai.pncp_open_opportunities (municipality_ibge_code);
create index if not exists pncp_open_opportunities_end_idx
  on licita_ai.pncp_open_opportunities (proposal_end);

create table if not exists licita_ai.pncp_open_sync_state (
  singleton boolean primary key default true check (singleton),
  status text not null default 'never_run',
  last_started_at timestamptz,
  last_completed_at timestamptz,
  total_records integer not null default 0,
  last_error text,
  updated_at timestamptz not null default now()
);

alter table licita_ai.pncp_open_opportunities enable row level security;
alter table licita_ai.pncp_open_sync_state enable row level security;
revoke all on licita_ai.pncp_open_opportunities, licita_ai.pncp_open_sync_state from anon, authenticated;
grant all on licita_ai.pncp_open_opportunities, licita_ai.pncp_open_sync_state to service_role;
