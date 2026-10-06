alter table licita_ai.companies
  add column if not exists natureza_juridica text,
  add column if not exists natureza_juridica_codigo text;
