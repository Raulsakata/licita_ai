-- Referências públicas do IBGE são atualizadas pelo worker e lidas da tabela
-- para evitar chamadas externas nos endpoints públicos de geografia.
create table if not exists licita_ai.geographic_reference (
  reference_key text primary key
    check (reference_key in ('ceara_municipalities', 'ceara_map')),
  payload jsonb not null,
  fetched_at timestamptz not null default now()
);

alter table licita_ai.geographic_reference enable row level security;
revoke all on licita_ai.geographic_reference from anon, authenticated;
grant all on licita_ai.geographic_reference to service_role;
