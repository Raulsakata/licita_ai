"""Aplica a migração inicial no PostgreSQL/Supabase usando DATABASE_URL."""
import sys
from pathlib import Path
try:
    import psycopg
except ModuleNotFoundError:
    psycopg = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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
    migrations_dir = ROOT / "supabase/migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))
    try:
        with psycopg.connect(settings.database_url) as connection:
            with connection.cursor() as cursor:
                for migration_file in migration_files:
                    cursor.execute(migration_file.read_text(encoding="utf-8"))
        print(f"Migrações aplicadas com sucesso: {', '.join(f.name for f in migration_files)}.")
        return 0
    except psycopg.Error as error:
        print(f"Falha ao aplicar migração: {error.__class__.__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
