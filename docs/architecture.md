# Arquitetura de dados e interface

## Fluxo de consulta

`IBGE (região → município/código)` → `PNCP (licitações do código IBGE)` → `Supabase (oportunidades)`.

Separadamente, `OpenCNPJ (CNPJ)` → normalização → regra ME/EPP + situação ativa → `Supabase (empresa e avaliação)`.

O código IBGE de sete posições é a chave territorial usada ao salvar e consultar oportunidades. Os dados originais das fontes são preservados em `raw_data`; os campos de uso frequente são normalizados em colunas para filtros e gráficos.

A API do PNCP exige `codigoModalidadeContratacao` (1 a 13) e `tamanhoPagina` entre 10 e 50 em toda consulta por data de publicação; a tabela de domínio das modalidades é servida por `GET /api/pncp/modalidades` para alimentar o filtro no frontend.

A API HTTP lê do armazenamento as licitações e as referências geográficas consumidas pelo painel público. A sincronização PNCP, a fila de captura HTML e a atualização diária de municípios/malha do IBGE são executadas pelo processo independente `worker.py`; a fila usa `FOR UPDATE SKIP LOCKED` para reservar lotes e permite retentativas sem manter o navegador ou as chamadas de origem dentro de uma requisição do usuário. Mantenha uma réplica do worker enquanto a sincronização periódica e a reserva de fila compartilharem o mesmo processo; escalonar réplicas exige primeiro adicionar um lock distribuído para a sincronização PNCP.

A captura HTML complementa o JSON do PNCP e nunca substitui os campos que não estão disponíveis na página. As respostas permanecem persistidas com hash SHA-256; identificadores de User-Agent devem identificar o coletor e incluir referência de contato, sem tentar contornar controles do portal. Dados de despesas por favorecido e natureza ainda não fazem parte deste modelo: precisam de ingestão e persistência próprias da API oficial do TCE-CE antes de serem exibidos como valores executados.

## Tabelas

| Tabela | Chave | Uso |
| --- | --- | --- |
| `licita_ai.companies` | `cnpj` | Cadastro normalizado e resposta OpenCNPJ |
| `licita_ai.eligibility_assessments` | `id` | Histórico da regra indicativa ME/EPP |
| `licita_ai.pncp_opportunities` | `pncp_id` | Oportunidade e município IBGE |
| `licita_ai.saved_searches` | `id` | Consultas reutilizáveis |

## Layout web

1. Barra lateral: navegação e fontes de dados.
2. Filtros: região, município, período e consulta PNCP.
3. Indicadores: município, total retornado e critério empresarial.
4. Área principal: tabela de oportunidades e cartão para consultar CNPJ.
5. Rodapé analítico: barra proporcional ao número de resultados.

Para um mapa regional de cobertura, recomenda-se um job agendado que percorra municípios em lotes, respeite os limites do PNCP e preencha uma tabela de agregados. Não é adequado fazer essa varredura inteira no clique do usuário.
