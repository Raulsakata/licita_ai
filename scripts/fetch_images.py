"""Baixa imagens (Wikipedia/Wikimedia Commons) das cidades do Ceará e de pontos turísticos e grava no banco.

Uso: python scripts/fetch_images.py [--force]
Por padrão só baixa o que ainda não está no banco.
"""
import argparse
import base64
import sys
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.db import get_db  # noqa: E402

WIKI = "https://pt.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "LicitaAI-estudantil/1.0 (https://github.com/Raulsakata/licita_ai)"}
THUMB = 640

TOURISM = {
    "tur-jericoacoara": ("Jericoacoara", ["Jericoacoara"]),
    "tur-canoa-quebrada": ("Canoa Quebrada", ["Canoa Quebrada"]),
    "tur-praia-iracema": ("Praia de Iracema, Fortaleza", ["Praia de Iracema"]),
    "tur-beach-park": ("Beach Park, Aquiraz", ["Beach Park"]),
    "tur-cumbuco": ("Cumbuco, Caucaia", ["Cumbuco"]),
    "tur-lencois-lagoa": ("Lagoinha, Paraipaba", ["Lagoinha (Paraipaba)", "Paraipaba"]),
    "tur-ibiapaba": ("Serra da Ibiapaba", ["Serra da Ibiapaba"]),
    "tur-guaramiranga": ("Guaramiranga", ["Guaramiranga"]),
    "tur-cariri": ("Juazeiro do Norte - Cariri", ["Juazeiro do Norte"]),
    "tur-mucuripe": ("Praia do Futuro, Fortaleza", ["Praia do Futuro (Fortaleza)", "Praia do Futuro"]),
    "tur-morro-branco": ("Morro Branco, Beberibe", ["Morro Branco"]),
    "tur-flecheiras": ("Flecheiras, Trairi", ["Flecheiras"]),
}


def page_image(client: httpx.Client, titles: list[str]) -> tuple[str, str, str] | None:
    for title in titles:
        params = {
            "action": "query", "format": "json", "redirects": 1, "prop": "pageimages|info",
            "piprop": "thumbnail|name", "pithumbsize": THUMB, "inprop": "url", "titles": title,
        }
        data = client.get(WIKI, params=params).json()
        for page in (data.get("query", {}).get("pages") or {}).values():
            thumb = (page.get("thumbnail") or {}).get("source")
            if thumb:
                return thumb, page.get("fullurl", ""), page.get("title", title)
    return None


def download(client: httpx.Client, url: str) -> tuple[bytes, str] | None:
    for attempt in range(4):
        response = client.get(url)
        if response.status_code == 429:
            time.sleep(3 * (attempt + 1))
            continue
        if response.status_code == 200 and response.content:
            return response.content, response.headers.get("content-type", "image/jpeg").split(";")[0]
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    db = get_db()
    if db is None:
        print("Supabase não configurado.")
        return 1
    table = db.schema("licita_ai").table("media_images")
    existing = set() if args.force else {r["key"] for r in table.select("key").execute().data or []}

    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        cities = client.get("https://servicodados.ibge.gov.br/api/v1/localidades/estados/23/municipios").json()
        jobs = [(str(c["id"]), "cidade", c["nome"], [f"{c['nome']} (Ceará)", f"{c['nome']}, Ceará", c["nome"]]) for c in cities]
        jobs = [(key, "turismo", title, names) for key, (title, names) in TOURISM.items()] + jobs
        ok = missing = 0
        for key, kind, title, names in jobs:
            if key in existing:
                ok += 1
                continue
            found = page_image(client, names)
            blob = download(client, found[0]) if found else None
            if not blob or len(blob[0]) > 400_000:
                missing += 1
                print(f"sem imagem: {title}")
                continue
            table.upsert({
                "key": key, "kind": kind, "title": title, "credit": f"Wikimedia Commons / Wikipédia — {found[2]}",
                "source_url": found[1], "content_type": blob[1], "data_b64": base64.b64encode(blob[0]).decode(),
            }, on_conflict="key").execute()
            ok += 1
            time.sleep(0.3)
    print(f"Concluído: {ok} com imagem, {missing} sem imagem.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
