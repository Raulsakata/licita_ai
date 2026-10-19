create table if not exists licita_ai.supplier_contracts (
  pncp_id text primary key,
  orgao_cnpj text not null,
  fornecedor_ni text not null,
  tipo_pessoa text,
  valor numeric,
  assinatura date,
  ano int,
  municipio_ibge text,
  created_at timestamptz not null default now()
);
create index if not exists supplier_contracts_forn_idx on licita_ai.supplier_contracts (fornecedor_ni);
create index if not exists supplier_contracts_ano_idx on licita_ai.supplier_contracts (ano);

create table if not exists licita_ai.supplier_profiles (
  cnpj text primary key,
  razao_social text,
  porte text,
  porte_grupo text not null default 'outras' check (porte_grupo in ('micro', 'pequena', 'outras')),
  mei boolean not null default false,
  uf text,
  municipio text,
  fetched_at timestamptz not null default now()
);

alter table licita_ai.supplier_contracts enable row level security;
alter table licita_ai.supplier_profiles enable row level security;
revoke all on licita_ai.supplier_contracts, licita_ai.supplier_profiles from anon, authenticated;
grant all on licita_ai.supplier_contracts, licita_ai.supplier_profiles to service_role;

create or replace function licita_ai.mpe_participation() returns jsonb
language sql stable as $$
  with c as (
    select s.ano, s.fornecedor_ni, s.valor, p.porte_grupo, p.mei, p.uf
    from licita_ai.supplier_contracts s
    join licita_ai.supplier_profiles p on p.cnpj = s.fornecedor_ni
  )
  select jsonb_build_object(
    'por_porte', coalesce((select jsonb_object_agg(g, v) from (
      select porte_grupo g, jsonb_build_object(
        'fornecedores', count(distinct fornecedor_ni),
        'fornecedores_ce', count(distinct fornecedor_ni) filter (where uf = 'CE'),
        'mei', count(distinct fornecedor_ni) filter (where mei),
        'contratos', count(*), 'valor', coalesce(sum(valor), 0)) v
      from c group by porte_grupo) t), '{}'::jsonb),
    'por_ano', coalesce((select jsonb_agg(linha order by ano) from (
      select ano, jsonb_build_object('ano', ano,
        'micro', count(distinct fornecedor_ni) filter (where porte_grupo = 'micro'),
        'pequena', count(distinct fornecedor_ni) filter (where porte_grupo = 'pequena'),
        'outras', count(distinct fornecedor_ni) filter (where porte_grupo = 'outras'),
        'valor_mpe', coalesce(sum(valor) filter (where porte_grupo in ('micro', 'pequena')), 0),
        'valor_total', coalesce(sum(valor), 0)) linha
      from c where ano is not null group by ano) t), '[]'::jsonb),
    'contratos_total', (select count(*) from licita_ai.supplier_contracts),
    'fornecedores_total', (select count(distinct fornecedor_ni) from licita_ai.supplier_contracts where tipo_pessoa = 'PJ'),
    'fornecedores_classificados', (select count(*) from licita_ai.supplier_profiles),
    'atualizado_em', (select max(fetched_at) from licita_ai.supplier_profiles)
  );
$$;
grant execute on function licita_ai.mpe_participation() to service_role;
