"""Aplica migrações PostgreSQL/Supabase usando DATABASE_URL."""
import argparse
import sys
from pathlib import Path
try:
    import psycopg
except ModuleNotFoundError:
    psycopg = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration", nargs="?", help="nome de um arquivo SQL para aplicar individualmente")
    args = parser.parse_args()
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
    if args.migration:
        migration_name = Path(args.migration)
        if migration_name.name != args.migration or migration_name.suffix != ".sql":
            print("Informe somente o nome de um arquivo .sql dentro de supabase/migrations.")
            return 1
        selected_migration = migrations_dir / migration_name
        if not selected_migration.is_file():
            print(f"Migração não encontrada: {migration_name.name}")
            return 1
        migration_files = [selected_migration]
    else:
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
