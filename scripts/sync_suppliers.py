"""Atualiza contratos e porte dos fornecedores (micro/pequenas) no banco. Uso: python scripts/sync_suppliers.py"""
import logging
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import suppliers  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print(suppliers.sync())
