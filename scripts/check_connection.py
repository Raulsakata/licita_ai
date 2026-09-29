"""Verifica a conexão com o banco Supabase usando DATABASE_URL do .env."""
import sys
from pathlib import Path

try:
    import psycopg
except ModuleNotFoundError:
    print("Dependência ausente. Execute: python -m pip install 'psycopg[binary]'")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]


def read_database_url() -> str | None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    return None


def main() -> int:
    url = read_database_url()
    if not url:
        print("DATABASE_URL não encontrada no .env.")
        return 1

    if "[YOUR-PASSWORD]" in url:
        print("ATENÇÃO: DATABASE_URL ainda contém o placeholder [YOUR-PASSWORD].")
        print("Substitua pela senha real do banco antes de testar.")
        return 1

    try:
        with psycopg.connect(url, connect_timeout=20) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select current_database(), current_user, version()")
                database, user, version = cursor.fetchone()
        print("Conexão OK")
        print(f"  banco: {database}")
        print(f"  usuário: {user}")
        print(f"  servidor: {version.split(',')[0]}")
        return 0
    except psycopg.OperationalError as error:
        print(f"Falha de conexão (OperationalError): {str(error)[:400]}")
        return 1
    except psycopg.Error as error:
        print(f"Falha (Error): {error.__class__.__name__} - {str(error)[:400]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())