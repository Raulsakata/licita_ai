"""Busca no Wikimedia Commons uma foto de ponto turístico (igreja, praça, praia, açude, serra...) de cada município
do Ceará e grava no banco (tabela media_images, kind 'cidade').

Uso: python scripts/fetch_tourist_images.py [--only-missing] [--limit N]
Sem opções, procura uma foto turística para todos os municípios e só substitui a existente quando encontra uma.
Municípios cujo crédito já começa com "Commons:" são ignorados (idempotente).
"""
import argparse
import base64
import sys
import time
import unicodedata
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.db import get_db  # noqa: E402

COMMONS = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "LicitaAI-estudantil/1.0 (https://github.com/Raulsakata/licita_ai)"}
QUERIES = ["{c} Ceará praia OR igreja OR matriz OR praça OR açude OR serra OR cachoeira OR lagoa OR museu OR mirante",
           "{c} Ceará turismo", "{c} Ceará"]
GOOD = ["praia", "igreja", "matriz", "praca", "acude", "serra", "cachoeira", "lagoa", "museu", "mirante", "balneario",
        "catedral", "santuario", "parque", "pico", "panoram", "vista", "centro", "capela", "sitio", "monumento", "orla"]
BAD = ["bandeira", "flag", "brasao", "coat", "mapa", "map", "logo", "localiza", "location", "escudo", "simbolo", "selo",
       "prefeitura", "camara", "eleic", "candidat", "retrato", "portrait", "grafico", "chart", "organograma", "icon"]


def norm(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def search(client: httpx.Client, query: str) -> list[dict]:
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 25,
              "gsrsearch": query, "prop": "imageinfo", "iiprop": "url|mime|size", "iiurlwidth": 640}
    for attempt in range(4):
        response = client.get(COMMONS, params=params)
        if response.status_code == 429:
            time.sleep(4 * (attempt + 1))
            continue
        if response.status_code != 200:
            return []
        return list((response.json().get("query", {}).get("pages") or {}).values())
    return []


def best(pages: list[dict], city: str) -> dict | None:
    name, ranked = norm(city), []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        title = norm(page.get("title", ""))
        if info.get("mime") != "image/jpeg" or not info.get("thumburl") or info.get("width", 0) < 800:
            continue
        if any(word in title for word in BAD) or name not in title:
            continue
        ranked.append((sum(word in title for word in GOOD), info.get("width", 0), page, info))
    if not ranked:
        return None
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return {"title": ranked[0][2]["title"], "info": ranked[0][3]}


def download(client: httpx.Client, url: str) -> bytes | None:
    for attempt in range(4):
        response = client.get(url)
        if response.status_code == 429:
            time.sleep(4 * (attempt + 1))
            continue
        return response.content if response.status_code == 200 and response.content else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    db = get_db()
    if db is None:
        print("Supabase não configurado.")
        return 1
    table = db.schema("licita_ai").table("media_images")
    rows = table.select("key,credit").eq("kind", "cidade").execute().data or []
    have = {row["key"]: row.get("credit") or "" for row in rows}
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        cities = client.get("https://servicodados.ibge.gov.br/api/v1/localidades/estados/23/municipios").json()
        found = skipped = missing = 0
        for number, city in enumerate(cities, 1):
            key = str(city["id"])
            if have.get(key, "").startswith("Commons:") or (args.only_missing and key in have):
                skipped += 1
                continue
            if args.limit and found + missing >= args.limit:
                break
            try:
                pick = None
                for template in QUERIES:
                    pick = best(search(client, template.format(c=city["nome"])), city["nome"])
                    time.sleep(0.4)
                    if pick:
                        break
                blob = download(client, pick["info"]["thumburl"]) if pick else None
                if not blob or len(blob) > 400_000:
                    blob = None
            except Exception as exc:
                print(f"erro {city['nome']}: {exc}")
                continue
            if not blob:
                missing += 1
                print(f"[{number}/{len(cities)}] sem foto turística: {city['nome']}", flush=True)
                continue
            table.upsert({
                "key": key, "kind": "cidade", "title": city["nome"],
                "credit": f"Commons: {pick['title'].removeprefix('File:')}",
                "source_url": pick["info"].get("descriptionurl", ""), "content_type": "image/jpeg",
                "data_b64": base64.b64encode(blob).decode(),
            }, on_conflict="key").execute()
            found += 1
            print(f"[{number}/{len(cities)}] {city['nome']}: {pick['title']}", flush=True)
    print(f"Concluído: {found} fotos, {missing} sem foto, {skipped} ignoradas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
