"""Contratos públicos de órgãos do Ceará (PNCP) e porte dos fornecedores (OpenCNPJ).

Grava em supplier_contracts / supplier_profiles apenas o que ainda não existe e expõe o resumo
de participação de micro e pequenas empresas via função SQL licita_ai.mpe_participation().
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import httpx
from src.config import settings
from src.db import get_db

logger = logging.getLogger(__name__)
PNCP_CONTRACTS = "https://pncp.gov.br/api/consulta/v1/contratos"
FIRST_DAY = date(2024, 1, 1)
RECENT_DAYS = 45
HEADERS = {"User-Agent": "LicitaAI-estudantil/1.0"}


def _schema():
    db = get_db()
    return db.schema("licita_ai") if db is not None else None


def _orgao_cnpjs(schema) -> list[str]:
    found, start = set(), 0
    while True:
        rows = schema.table("pncp_opportunities").select("pncp_id").eq("uf", "CE").range(start, start + 999).execute().data or []
        found.update(row["pncp_id"].split("-")[0] for row in rows if row.get("pncp_id"))
        if len(rows) < 1000:
            return sorted(found)
        start += 1000


def _get(client: httpx.Client, url: str, params: dict | None = None) -> httpx.Response | None:
    for attempt in range(4):
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError:
            time.sleep(2 * (attempt + 1))
            continue
        if response.status_code in (429, 500, 502, 503, 504):
            time.sleep(3 * (attempt + 1))
            continue
        return response
    return None


def _contract_row(item: dict, orgao: str) -> dict | None:
    ni = "".join(ch for ch in str(item.get("niFornecedor") or "") if ch.isdigit())
    if not item.get("numeroControlePNCP") or not ni:
        return None
    signed = item.get("dataAssinatura")
    return {
        "pncp_id": item["numeroControlePNCP"], "orgao_cnpj": orgao, "fornecedor_ni": ni, "tipo_pessoa": item.get("tipoPessoa"),
        "valor": item.get("valorGlobal") or item.get("valorInicial"), "assinatura": signed,
        "ano": int(signed[:4]) if signed else item.get("anoContrato"),
        "municipio_ibge": (item.get("unidadeOrgao") or {}).get("codigoIbge"),
    }


def sync_contracts(schema, client: httpx.Client) -> int:
    table = schema.table("supplier_contracts")
    has_data = bool(table.select("pncp_id").limit(1).execute().data)
    start = date.today() - timedelta(days=RECENT_DAYS) if has_data else FIRST_DAY
    added = 0
    orgaos = _orgao_cnpjs(schema)
    logger.info("Contratos: %s órgãos desde %s", len(orgaos), start)
    for index, orgao in enumerate(orgaos, 1):
        page = 1
        while True:
            response = _get(client, PNCP_CONTRACTS, {"dataInicial": start.strftime("%Y%m%d"), "dataFinal": date.today().strftime("%Y%m%d"),
                                                      "cnpjOrgao": orgao, "pagina": page, "tamanhoPagina": 500})
            if response is None or response.status_code != 200:
                break
            body = response.json()
            rows = [row for row in (_contract_row(item, orgao) for item in body.get("data") or []) if row]
            if rows:
                table.upsert(rows, on_conflict="pncp_id", ignore_duplicates=True).execute()
                added += len(rows)
            if page >= int(body.get("totalPaginas") or 1):
                break
            page += 1
        if index % 50 == 0:
            logger.info("Contratos: %s/%s órgãos", index, len(orgaos))
    return added


def _classify(cnpj: str, client: httpx.Client) -> dict | None:
    response = _get(client, f"{settings.open_cnpj_base_url}/{cnpj}")
    if response is None or response.status_code not in (200, 404):
        return None
    data = response.json() if response.status_code == 200 else {}
    porte = (data.get("porte_empresa") or "").lower()
    group = "micro" if "micro" in porte else "pequena" if "pequeno" in porte else "outras"
    return {"cnpj": cnpj, "razao_social": data.get("razao_social"), "porte": data.get("porte_empresa") or "N/I", "porte_grupo": group,
            "mei": data.get("opcao_mei") == "S", "uf": data.get("uf"), "municipio": data.get("municipio")}


def sync_profiles(schema, client: httpx.Client, limit: int | None = None) -> int:
    known, start = set(), 0
    while True:
        rows = schema.table("supplier_profiles").select("cnpj").range(start, start + 999).execute().data or []
        known.update(row["cnpj"] for row in rows)
        if len(rows) < 1000:
            break
        start += 1000
    wanted, start = set(), 0
    while True:
        rows = schema.table("supplier_contracts").select("fornecedor_ni").eq("tipo_pessoa", "PJ").range(start, start + 999).execute().data or []
        wanted.update(row["fornecedor_ni"] for row in rows if len(row["fornecedor_ni"]) == 14)
        if len(rows) < 1000:
            break
        start += 1000
    pending = sorted(wanted - known)[:limit]
    logger.info("Fornecedores a classificar: %s", len(pending))
    done = 0
    for offset in range(0, len(pending), 200):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = [row for row in pool.map(lambda c: _classify(c, client), pending[offset:offset + 200]) if row]
        if results:
            schema.table("supplier_profiles").upsert(results, on_conflict="cnpj", ignore_duplicates=True).execute()
            done += len(results)
        logger.info("Classificados %s/%s", done, len(pending))
    return done


def sync(limit: int | None = None) -> dict:
    schema = _schema()
    if schema is None:
        return {"status": "sem_banco"}
    with httpx.Client(headers=HEADERS, timeout=60) as client:
        contracts = sync_contracts(schema, client)
        profiles = sync_profiles(schema, client, limit)
    return {"status": "ok", "contratos": contracts, "fornecedores": profiles}


def participation() -> dict:
    schema = _schema()
    if schema is None:
        return {}
    return schema.rpc("mpe_participation").execute().data or {}
