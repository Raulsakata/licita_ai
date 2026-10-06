create table if not exists licita_ai.pncp_sync_windows (
  id bigint generated always as identity primary key,
  modality_code smallint not null check (modality_code between 1 and 13),
  starts_on date not null,
  ends_on date not null,
  total_records integer not null default 0,
  stored_records integer not null default 0,
  fetched_at timestamptz not null default now(),
  constraint pncp_sync_windows_dates_check check (starts_on <= ends_on),
  constraint pncp_sync_windows_unique unique (modality_code, starts_on, ends_on)
);
create index if not exists pncp_sync_windows_range_idx
  on licita_ai.pncp_sync_windows (modality_code, starts_on, ends_on);

create table if not exists licita_ai.pncp_sync_state (
  singleton boolean primary key default true check (singleton),
  status text not null default 'never_run',
  last_started_at timestamptz,
  last_completed_at timestamptz,
  last_error text,
  updated_at timestamptz not null default now()
);
alter table licita_ai.pncp_sync_windows enable row level security;
alter table licita_ai.pncp_sync_state enable row level security;
revoke all on licita_ai.pncp_sync_windows, licita_ai.pncp_sync_state from anon, authenticated;
grant all on licita_ai.pncp_sync_windows, licita_ai.pncp_sync_state to service_role;
grant usage, select on sequence licita_ai.pncp_sync_windows_id_seq to service_role;
