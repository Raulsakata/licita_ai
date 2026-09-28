"""Testa conexão, schema e uma gravação PostgreSQL sem manter dados de teste."""
import re
import sys
from pathlib import Path
try:
    import psycopg
except ModuleNotFoundError:
    psycopg = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPECTED_TABLES = {"companies", "eligibility_assessments", "pncp_opportunities", "saved_searches"}


def main() -> int:
    if psycopg is None:
        print("Dependência ausente. Execute: python -m pip install -r requirements.txt")
        return 1
    try:
        from src.config import settings
    except ModuleNotFoundError:
        print("Dependência ausente. Execute: python -m pip install -r requirements.txt")
        return 1
    if not settings.database_url:
        print("DATABASE_URL não configurada no .env.")
        return 1
    if "[YOUR-PASSWORD]" in settings.database_url:
        print("DATABASE_URL ainda contém o placeholder [YOUR-PASSWORD].")
        print("Use a URI de conexão atual do Supabase com a senha real do banco.")
        return 1
    try:
        with psycopg.connect(settings.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select table_name from information_schema.tables where table_schema = 'licita_ai'")
                found = {row[0] for row in cursor.fetchall()}
                missing = EXPECTED_TABLES - found
                if missing:
                    print(f"Tabelas ausentes: {', '.join(sorted(missing))}")
                    return 1
                cursor.execute("insert into licita_ai.saved_searches (name, filters) values (%s, %s::jsonb) returning id", ("__connection_test__", '{"source":"test"}'))
                record_id = cursor.fetchone()[0]
                cursor.execute("select name from licita_ai.saved_searches where id = %s", (record_id,))
                assert cursor.fetchone()[0] == "__connection_test__"
                cursor.execute("delete from licita_ai.saved_searches where id = %s", (record_id,))
        print("Teste concluído: conexão, schema, gravação, leitura e limpeza estão corretos.")
        return 0
    except (psycopg.Error, AssertionError) as error:
        message = str(error)
        if settings.database_url:
            message = message.replace(settings.database_url, "[DATABASE_URL]")
        message = re.sub(r"(?i)(postgres(?:ql)?://[^:/@\s]+:)[^@/\s]+@", r"\1[REDACTED]@", message)
        print(f"Falha no teste do banco: {error.__class__.__name__}: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
