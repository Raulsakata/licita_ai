import asyncio
from collections import defaultdict
from datetime import date, datetime
from src.extract import get_pncp_contracts, get_pncp_proposals

UF = "CE"
IBGE_UF_CODE = "23"
DEFAULT_MODALITIES = (4, 6, 8)
PAGE_SIZE = 50
MAX_PAGES = 3
MAX_PERIOD_DAYS = 400

ME_EPP_TERMS = (
    "microempresa", "microempresas", "empresa de pequeno porte", "empresas de pequeno porte",
    "me/epp", "me e epp", "exclusiva para me", "exclusivo para me", "cota reservada",
)


def has_me_epp_signal(item: dict) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("objetoCompra", "informacaoComplementar")).casefold()
    return any(term in text for term in ME_EPP_TERMS)


def is_ceara(item: dict) -> bool:
    unit = item.get("unidadeOrgao") or {}
    uf = unit.get("ufSigla")
    if uf:
        return uf == UF
    return str(unit.get("codigoIbge") or item.get("codigoMunicipioIbge") or "").startswith(IBGE_UF_CODE)


def item_value(item: dict) -> float:
    try:
        return float(item.get("valorTotalEstimado") or 0)
    except (TypeError, ValueError):
        return 0.0


def shape_item(item: dict) -> dict:
    unit = item.get("unidadeOrgao") or {}
    organ = item.get("orgaoEntidade") or {}
    link = None
    origin_link = item.get("linkSistemaOrigem")
    if organ.get("cnpj") and item.get("anoCompra") and item.get("sequencialCompra"):
        link = f"https://pncp.gov.br/app/editais/{organ['cnpj']}/{item['anoCompra']}/{item['sequencialCompra']}"
    return {
        "id": item.get("numeroControlePNCP"),
        "objeto": item.get("objetoCompra"),
        "orgao": organ.get("razaoSocial") or unit.get("nomeUnidade"),
        "municipio": unit.get("municipioNome"),
        "municipio_ibge": unit.get("codigoIbge"),
        "modalidade": item.get("modalidadeNome"),
        "valor": item_value(item),
        "publicacao": item.get("dataPublicacaoPncp"),
        "abertura_propostas": item.get("dataAberturaProposta"),
        "encerramento_propostas": item.get("dataEncerramentoProposta"),
        "situacao": item.get("situacaoCompraNome"),
        "numero": item.get("numeroCompra"),
        "processo": item.get("processo"),
        "informacao_complementar": item.get("informacaoComplementar"),
        "exige_porte_me_epp": has_me_epp_signal(item),
        "link_edital": link,
        "link_origem": origin_link if str(origin_link or "").lower().startswith(("http://", "https://")) else None,
    }


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def shift_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


async def _fetch_modality(modality: int, start: date, end: date, municipality: str | None, pages: int, semaphore: asyncio.Semaphore):
    base = {
        "dataInicial": start.strftime("%Y%m%d"), "dataFinal": end.strftime("%Y%m%d"),
        "codigoModalidadeContratacao": modality, "tamanhoPagina": PAGE_SIZE,
    }
    base.update({"codigoMunicipioIbge": municipality} if municipality else {"uf": UF})

    async def page(number: int):
        async with semaphore:
            return await get_pncp_contracts({**base, "pagina": number})

    first = await page(1)
    items = list(first.get("data") or [])
    total = int(first.get("totalRegistros") or len(items))
    last_page = min(int(first.get("totalPaginas") or 1), pages)
    complete = True
    if last_page > 1:
        rest = await asyncio.gather(*(page(n) for n in range(2, last_page + 1)), return_exceptions=True)
        for response in rest:
            if isinstance(response, Exception):
                complete = False
            else:
                items.extend(response.get("data") or [])
    return total, items, complete and len(items) >= total


async def collect(start: date, end: date, municipality: str | None = None, modalities=DEFAULT_MODALITIES, pages: int = MAX_PAGES):
    """Retorna (total_reportado, itens_do_CE, amostra_completa, consulta_sem_falhas)."""
    semaphore = asyncio.Semaphore(4)
    results = await asyncio.gather(*(_fetch_modality(m, start, end, municipality, pages, semaphore) for m in modalities), return_exceptions=True)
    total, unique, sample_complete, no_failures = 0, {}, True, True
    for result in results:
        if isinstance(result, Exception):
            no_failures = False
            continue
        group_total, items, complete = result
        total += group_total
        sample_complete = sample_complete and complete
        for item in items:
            key = item.get("numeroControlePNCP")
            if key and is_ceara(item):
                unique[key] = item
    return total, list(unique.values()), sample_complete, no_failures


def is_closed(item: dict, now_iso: str | None = None) -> bool:
    closing = str(item.get("dataEncerramentoProposta") or "")
    return bool(closing) and closing < (now_iso or datetime.now().isoformat())


def closed_mpe_by_month(items: list[dict]) -> list[dict]:
    """Participação de ME/EPP nas licitações já encerradas, agrupadas pelo mês de encerramento."""
    now_iso = datetime.now().isoformat()
    months: dict[str, dict] = defaultdict(lambda: {"encerradas": 0, "encerradas_mpe": 0, "valor_mpe": 0.0, "valor_encerradas": 0.0})
    for item in items:
        if not is_closed(item, now_iso):
            continue
        bucket = months[str(item["dataEncerramentoProposta"])[:7]]
        bucket["encerradas"] += 1
        bucket["valor_encerradas"] += item_value(item)
        if has_me_epp_signal(item):
            bucket["encerradas_mpe"] += 1
            bucket["valor_mpe"] += item_value(item)
    return [{"mes": month, **data, "participacao_mpe": data["encerradas_mpe"] / data["encerradas"]} for month, data in sorted(months.items())]


def summarize(items: list[dict], reported_total: int) -> dict:
    by_city: dict[str, dict] = defaultdict(lambda: {"quantidade": 0, "valor": 0.0})
    by_month: dict[str, dict] = defaultdict(lambda: {"quantidade": 0, "valor": 0.0})
    by_modality: dict[str, dict] = defaultdict(lambda: {"quantidade": 0, "valor": 0.0})
    total_value = 0.0
    mpe_count = 0
    for item in items:
        value = item_value(item)
        total_value += value
        mpe_count += has_me_epp_signal(item)
        city = (item.get("unidadeOrgao") or {}).get("municipioNome") or "Não informado"
        month = str(item.get("dataPublicacaoPncp") or "")[:7] or "N/I"
        for bucket, key in ((by_city, city), (by_month, month), (by_modality, item.get("modalidadeNome") or "Outras")):
            bucket[key]["quantidade"] += 1
            bucket[key]["valor"] += value
    rank = lambda bucket, name: sorted(({name: key, **data} for key, data in bucket.items()), key=lambda row: row["valor"], reverse=True)
    return {
        "quantidade_total": max(reported_total, len(items)),
        "quantidade_amostra": len(items),
        "valor_total": total_value,
        "valor_medio": total_value / len(items) if items else 0.0,
        "quantidade_mpe": mpe_count,
        "por_municipio": rank(by_city, "municipio"),
        "por_mes": sorted(({"mes": key, **data} for key, data in by_month.items()), key=lambda row: row["mes"]),
        "por_modalidade": rank(by_modality, "modalidade"),
    }


async def fetch_open(municipality: str | None, today: date, limit: int = 50, pages: int = 1):
    base = {"dataFinal": today.strftime("%Y%m%d"), "tamanhoPagina": PAGE_SIZE}
    base.update({"codigoMunicipioIbge": municipality} if municipality else {"uf": UF})
    response = await get_pncp_proposals({**base, "pagina": 1})
    raw = list(response.get("data") or [])
    total = int(response.get("totalRegistros") or len(raw))
    last_page = min(int(response.get("totalPaginas") or 1), pages)
    if last_page > 1:
        semaphore = asyncio.Semaphore(4)

        async def page(number: int):
            async with semaphore:
                return await get_pncp_proposals({**base, "pagina": number})

        rest = await asyncio.gather(*(page(n) for n in range(2, last_page + 1)), return_exceptions=True)
        for extra in rest:
            if not isinstance(extra, Exception):
                raw.extend(extra.get("data") or [])
    unique = {item.get("numeroControlePNCP"): item for item in raw if is_ceara(item) and item.get("numeroControlePNCP")}
    items = sorted(unique.values(), key=lambda item: str(item.get("dataEncerramentoProposta") or ""))
    return total, items[:limit]
