-- Autenticação de empresas, logs do sistema e restrição geográfica ao Ceará.
alter table licita_ai.companies
  add column if not exists password_hash text,
  add column if not exists ativo boolean not null default true,
  add column if not exists last_login_at timestamptz;

alter table licita_ai.pncp_opportunities
  add column if not exists uf text,
  add column if not exists estimated_value numeric;

create index if not exists pncp_opportunities_uf_idx on licita_ai.pncp_opportunities(uf);

create table if not exists licita_ai.system_logs (
  id uuid primary key default gen_random_uuid(),
  level text not null default 'info',
  event text not null,
  actor text not null default 'sistema',
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists system_logs_created_idx on licita_ai.system_logs(created_at desc);
alter table licita_ai.system_logs enable row level security;

-- Somente a API (service role) lê/grava estas tabelas; o navegador nunca acessa o schema diretamente.
revoke all on licita_ai.companies, licita_ai.system_logs from anon, authenticated;
grant all on licita_ai.system_logs to service_role;

-- Mantém apenas oportunidades do Ceará (IBGE UF 23).
delete from licita_ai.pncp_opportunities
where coalesce(uf, raw_data->'unidadeOrgao'->>'ufSigla') is distinct from 'CE'
  and coalesce(municipality_ibge_code, '') not like '23%';
