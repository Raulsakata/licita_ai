-- Em projetos Supabase, o banco físico normalmente é "postgres". Este schema
-- fornece o namespace lógico solicitado: licita_ai.
create extension if not exists pgcrypto;
create schema if not exists licita_ai;

create table if not exists licita_ai.companies (
  cnpj text primary key check (char_length(cnpj) = 14),
  razao_social text,
  nome_fantasia text,
  porte text,
  situacao_cadastral text,
  cnae_principal text,
  raw_data jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists licita_ai.eligibility_assessments (
  id uuid primary key default gen_random_uuid(),
  cnpj text not null references licita_ai.companies(cnpj),
  micro_ou_pequena boolean not null,
  apta_indicativamente boolean not null,
  motivo text not null,
  created_at timestamptz not null default now()
);

create table if not exists licita_ai.pncp_opportunities (
  pncp_id text primary key,
  municipality_ibge_code text check (char_length(municipality_ibge_code) = 7),
  title text,
  modality text,
  publication_date timestamptz,
  raw_data jsonb not null,
  updated_at timestamptz not null default now()
);

-- Compatibilidade caso esta migração tenha sido executada na primeira versão.
alter table licita_ai.pncp_opportunities add column if not exists municipality_ibge_code text;
alter table licita_ai.pncp_opportunities add column if not exists title text;
alter table licita_ai.pncp_opportunities add column if not exists modality text;
alter table licita_ai.pncp_opportunities add column if not exists publication_date timestamptz;
create index if not exists pncp_opportunities_municipality_idx on licita_ai.pncp_opportunities(municipality_ibge_code);

create table if not exists licita_ai.saved_searches (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 120),
  filters jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table licita_ai.companies enable row level security;
alter table licita_ai.eligibility_assessments enable row level security;
alter table licita_ai.pncp_opportunities enable row level security;
alter table licita_ai.saved_searches enable row level security;

-- A API usa a chave service role. Quando a autenticação de usuários for adicionada,
-- inclua políticas por usuário antes de acessar esta tabela pelo navegador.
