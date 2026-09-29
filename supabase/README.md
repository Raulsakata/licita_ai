# Supabase — Licita AI

1. Conecte este projeto ao projeto Supabase **licita_ai**.
2. Preencha `DATABASE_URL` no `.env` local com a senha do banco.
3. Aplique a migração com `python scripts/apply_migration.py`.
4. Execute `python scripts/test_database.py` para validar conexão, schema, escrita, leitura e limpeza.
3. Defina `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` apenas no ambiente da API/Render; nunca no frontend ou no Git.

## Verificação após a migração

```sql
select table_schema, table_name
from information_schema.tables
where table_schema = 'licita_ai'
order by table_name;
```

Devem existir: `companies`, `eligibility_assessments`, `pncp_opportunities` e `saved_searches`.
