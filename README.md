# Licita AI

Plataforma web para consultar oportunidades de contratação pública no Nordeste. Integra PNCP, OpenCNPJ, IBGE e Supabase pelo backend FastAPI.

## Arquitetura

- `apps/web`: React + Vite, painel de pesquisa.
- `src`: API FastAPI organizada por responsabilidade, como `extract`, `transform`, `mappers` e `validators`.
- `supabase/migrations`: estrutura inicial do banco.
- `render.yaml`: infraestrutura declarativa para o Render.

## Rodar localmente

Pré-requisitos: Python 3.12+ e Node.js 20+.

1. Copie `.env.example` para `.env` e configure `SUPABASE_URL` e `SUPABASE_SECRET_KEY` somente no backend. Não use `VITE_` em variáveis secretas.
2. Execute `python -m venv .venv` e ative o ambiente virtual.
3. Execute `pip install -r requirements.txt`; em outro terminal, execute `npm install`.
4. Execute `python main.py` e, em outro terminal, `npm run dev -w @licita/web`.
5. Abra `http://localhost:5173`.

Alternativamente, com Docker: `docker compose up --build`. A API fica em `http://localhost:3000` e o web em `http://localhost:8080`.

## Supabase

Crie um projeto no Supabase e execute, em ordem, todos os arquivos em `supabase/migrations/`. O Supabase gerenciado costuma manter o banco físico padrão `postgres`; as migrações criam o schema lógico `licita_ai`. A API aceita `SUPABASE_SECRET_KEY` e mantém compatibilidade com `SUPABASE_SERVICE_ROLE_KEY`; ambas são exclusivamente de servidor e nunca devem ser expostas ao frontend.

As consultas ao PNCP são persistidas em `licita_ai.pncp_opportunities`. A rota `GET /api/empresas/{cnpj}/elegibilidade` consulta o OpenCNPJ, persiste o cadastro e busca propostas abertas nas nove UFs do Nordeste. A avaliação é indicativa: porte, natureza jurídica e situação cadastral não substituem a conferência do objeto social, requisitos e edital.

As respostas públicas do PNCP ficam em cache em memória por 5 minutos, as do OpenCNPJ por 6 horas e as do IBGE por 24 horas. Chamadas externas têm timeout e repetição limitada para `429`, erros `5xx` e falhas de transporte. Ajuste TTLs e tentativas pelas variáveis em `.env.example`. O cache é local ao processo e não substitui um cache compartilhado em deploy com múltiplas instâncias.

O painel conta Pregões Eletrônicos publicados no último mês. O valor associado a ME/EPP é uma estimativa parcial baseada em até 50 registros por UF com menção textual explícita; não representa o valor total oficial de todas as cotas ou itens reservados.

## APIs e rotas

- IBGE: `GET /api/geografia/regioes` retorna somente o Nordeste; `GET /api/geografia/regioes/{id}/municipios` aceita a região Nordeste (`id=2`).
- Painel: `GET /api/visao-geral` retorna os indicadores regionais.
- PNCP — tabela de modalidades: `GET /api/pncp/modalidades` (domínio fixo, códigos 1 a 13).
- PNCP por cidade: `GET /api/municipios/{codigo_ibge}/licitacoes` — `codigoModalidadeContratacao` é **obrigatório** (exigência da própria API do PNCP) e `tamanhoPagina` deve estar entre 10 e 50.
- PNCP geral: `GET /api/pncp/contratacoes` — exige UF nordestina e aplica as regras de `codigoModalidadeContratacao` e `tamanhoPagina` acima.
- OpenCNPJ e avaliação: `GET /api/empresas/{cnpj}/elegibilidade`.
- Consultas salvas: `GET /api/consultas-salvas`, `POST /api/consultas-salvas` e `DELETE /api/consultas-salvas/{id}` (persistidas em `licita_ai.saved_searches`).

> Nota: a API é exclusivamente o FastAPI em `src/api.py` (servida pelo `Dockerfile` na raiz via `render.yaml`). Uma implementação Node/Express paralela e não utilizada (`apps/api`) foi removida do repositório.

Veja a arquitetura de dados e do painel em `docs/architecture.md`.

## Testes

Com as dependências instaladas no ambiente Python do projeto, execute `python -m unittest discover -s tests -v`. Os testes usam respostas simuladas e não precisam de credenciais nem de chamadas externas.

## Deploy

1. Crie um repositório GitHub e envie o código.
2. No Render, escolha **New > Blueprint** e conecte o repositório. O `render.yaml` criará os serviços.
3. Defina `SUPABASE_URL` e `SUPABASE_SECRET_KEY` como segredos na API; defina `FRONTEND_ORIGIN` com a URL final do frontend.
4. Após o primeiro deploy da API, defina `VITE_API_URL` no serviço web com a URL pública da API e faça novo deploy do web.

O endpoint de saúde da API é `/health`. A consulta PNCP é exposta em `/api/pncp/contratacoes`.
