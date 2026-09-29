-- Corrige permissao: o schema licita_ai nunca foi exposto ao PostgREST nem recebeu GRANTs.
grant usage on schema licita_ai to service_role, authenticated, anon;

grant all on all tables in schema licita_ai to service_role;
grant select, insert, update, delete on all tables in schema licita_ai to authenticated;

alter default privileges in schema licita_ai grant all on tables to service_role;
alter default privileges in schema licita_ai grant select, insert, update, delete on tables to authenticated;

-- PostgREST so acessa schemas listados aqui; adiciona licita_ai aos ja expostos.
alter role authenticator set pgrst.db_schemas = 'public, graphql_public, licita_ai';
notify pgrst, 'reload config';
