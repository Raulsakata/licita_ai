# Arquitetura de dados e interface

## Fluxo de consulta

`IBGE (região → município/código)` → `PNCP (licitações do código IBGE)` → `Supabase (oportunidades)`.

Separadamente, `OpenCNPJ (CNPJ)` → normalização → regra ME/EPP + situação ativa → `Supabase (empresa e avaliação)`.

O código IBGE de sete posições é a chave territorial usada ao salvar e consultar oportunidades. Os dados originais das fontes são preservados em `raw_data`; os campos de uso frequente são normalizados em colunas para filtros e gráficos.

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
