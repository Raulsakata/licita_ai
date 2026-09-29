# Licita AI

Plataforma web para consultar e organizar oportunidades de contratação pública. A primeira fonte conectada é o [PNCP](https://pncp.gov.br), por meio da API pública de consultas.

## Arquitetura

- `apps/web`: React + Vite, painel de pesquisa.
- `src`: API FastAPI organizada por responsabilidade, como `extract`, `transform`, `mappers` e `validators`.
- `supabase/migrations`: estrutura inicial do banco.
- `render.yaml`: infraestrutura declarativa para o Render.

## Rodar localmente

Pré-requisitos: Python 3.12+ e Node.js 20+.

1. Copie `.env.example` para `.env` e preencha as variáveis do Supabase.
2. Execute `python -m venv .venv` e ative o ambiente virtual.
3. Execute `pip install -r requirements.txt`; em outro terminal, execute `npm install`.
4. Execute `python main.py` e, em outro terminal, `npm run dev -w @licita/web`.
4. Abra `http://localhost:5173`.

Alternativamente, com Docker: `docker compose up --build`. A API fica em `http://localhost:3000` e o web em `http://localhost:8080`.

## Supabase

Crie um projeto chamado **licita_ai** no Supabase e execute o SQL em `supabase/migrations/0001_initial.sql` no SQL Editor. O Supabase gerenciado costuma manter o banco físico padrão `postgres`; a migração cria o schema lógico `licita_ai`, onde todos os dados do projeto são salvos. Nunca exponha `SUPABASE_SERVICE_ROLE_KEY` ao frontend; ela é usada somente pela API.

As consultas ao PNCP são persistidas em `licita_ai.pncp_opportunities`. A rota `GET /api/empresas/{cnpj}/elegibilidade` consulta o OpenCNPJ, persiste o cadastro e registra a avaliação indicativa. Apenas empresas ME/EPP e ativas são marcadas como aptas indicativamente; isso não substitui a habilitação prevista em edital.

## APIs e rotas

- IBGE: `GET /api/geografia/regioes` e `GET /api/geografia/regioes/{id}/municipios`.
- PNCP — tabela de modalidades: `GET /api/pncp/modalidades` (domínio fixo, códigos 1 a 13).
- PNCP por cidade: `GET /api/municipios/{codigo_ibge}/licitacoes` — `codigoModalidadeContratacao` é **obrigatório** (exigência da própria API do PNCP) e `tamanhoPagina` deve estar entre 10 e 50.
- PNCP geral: `GET /api/pncp/contratacoes` — mesmas regras de `codigoModalidadeContratacao` e `tamanhoPagina` acima.
- OpenCNPJ e avaliação: `GET /api/empresas/{cnpj}/elegibilidade`.
- Consultas salvas: `GET /api/consultas-salvas`, `POST /api/consultas-salvas` e `DELETE /api/consultas-salvas/{id}` (persistidas em `licita_ai.saved_searches`).

> Nota: `apps/api` (Node/Express) é uma implementação legada e não é usada no deploy — o `render.yaml` publica a API a partir do `Dockerfile` na raiz, que roda o FastAPI (`src/api.py`).

Veja a arquitetura de dados e do painel em `docs/architecture.md`.

## Deploy

1. Crie um repositório GitHub e envie o código.
2. No Render, escolha **New > Blueprint** e conecte o repositório. O `render.yaml` criará os serviços.
3. Defina os segredos `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` na API; defina `FRONTEND_ORIGIN` com a URL final do frontend.
4. Após o primeiro deploy da API, defina `VITE_API_URL` no serviço web com a URL pública da API e faça novo deploy do web.

O endpoint de saúde da API é `/health`. A consulta PNCP é exposta em `/api/pncp/contratacoes`.
