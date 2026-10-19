-- Índices parciais aceleram os filtros reais do painel, que consulta somente
-- registros do Ceará por intervalo de publicação e, opcionalmente, município.
create index if not exists pncp_opportunities_ce_period_idx
  on licita_ai.pncp_opportunities (publication_date, municipality_ibge_code)
  where uf = 'CE';

create index if not exists pncp_opportunities_ce_city_period_idx
  on licita_ai.pncp_opportunities (municipality_ibge_code, publication_date)
  where uf = 'CE';

-- A ordem das colunas corresponde às consultas de editais abertos: por prazo
-- em todo o estado ou por município e prazo, sempre com UF limitada ao Ceará.
create index if not exists pncp_open_opportunities_ce_deadline_idx
  on licita_ai.pncp_open_opportunities (proposal_end, municipality_ibge_code)
  where uf = 'CE';

create index if not exists pncp_open_opportunities_ce_city_deadline_idx
  on licita_ai.pncp_open_opportunities (municipality_ibge_code, proposal_end)
  where uf = 'CE';
