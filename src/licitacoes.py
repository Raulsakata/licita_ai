import asyncio
from collections import defaultdict
from datetime import date, datetime
from src.extract import (
    get_pncp_contracts, get_pncp_proposals,
    invalidate_pncp_contract_page, invalidate_pncp_proposal_page,
)

UF = "CE"
IBGE_UF_CODE = "23"
DEFAULT_MODALITIES = (4, 6, 8)
PAGE_SIZE = 50
PAGE_BATCH_SIZE = 40
PAGE_CONCURRENCY = 4
PAGE_FETCH_ATTEMPTS = 3
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


async def _fetch_page_with_retries(fetch_page, number: int, expected_count: int | None = None):
    last_error = None
    for attempt in range(PAGE_FETCH_ATTEMPTS):
        try:
            response = await fetch_page(number, refresh=attempt > 0)
            page_items = response.get("data") or [] if isinstance(response, dict) else []
            required_count = expected_count
            if required_count is None:
                try:
                    reported_total = int(response.get("totalRegistros") or 0) if isinstance(response, dict) else 0
                    reported_pages = int(response.get("totalPaginas") or 0) if isinstance(response, dict) else 0
                except (TypeError, ValueError):
                    reported_total, reported_pages = 0, 0
                has_page_total = isinstance(response, dict) and response.get("totalRegistros") is not None
                has_page_count = isinstance(response, dict) and response.get("totalPaginas") is not None
                if has_page_total:
                    required_count = min(PAGE_SIZE, reported_total)
                elif has_page_count:
                    if reported_pages > number:
                        required_count = PAGE_SIZE
                    else:
                        required_count = 1 if reported_pages > 1 else 0
                else:
                    required_count = 1
            if isinstance(response, dict) and len(page_items) >= required_count:
                return response
            last_error = RuntimeError(f"PNCP retornou {len(page_items)} de {required_count} itens na página {number}")
        except Exception as error:
            last_error = error
        if attempt + 1 < PAGE_FETCH_ATTEMPTS:
            await asyncio.sleep(min(0.25 * (2 ** attempt), 2.0))
    raise last_error or RuntimeError(f"Não foi possível carregar a página {number} do PNCP")


async def _load_all_pages(first_response: dict, fetch_page) -> tuple[int, list[dict], bool, bool]:
    first_items = list(first_response.get("data") or [])
    has_total = first_response.get("totalRegistros") is not None
    has_pages = first_response.get("totalPaginas") is not None
    try:
        reported_total = int(first_response.get("totalRegistros") or 0)
        reported_pages = int(first_response.get("totalPaginas") or 0)
    except (TypeError, ValueError):
        reported_total, reported_pages = 0, 0
    expected_pages = max(1, reported_pages, (reported_total + PAGE_SIZE - 1) // PAGE_SIZE)
    items = first_items
    no_failures = True

    for batch_start in range(2, expected_pages + 1, PAGE_BATCH_SIZE):
        batch_end = min(batch_start + PAGE_BATCH_SIZE, expected_pages + 1)
        responses = await asyncio.gather(
            *(
                _fetch_page_with_retries(
                    fetch_page,
                    number,
                    min(PAGE_SIZE, max(0, reported_total - (number - 1) * PAGE_SIZE)) if has_total else (
                        PAGE_SIZE if number < expected_pages else (1 if expected_pages > 1 else 0)
                    ),
                )
                for number in range(batch_start, batch_end)
            ),
            return_exceptions=True,
        )
        for response in responses:
            if isinstance(response, Exception) or not isinstance(response, dict):
                no_failures = False
                continue
            items.extend(response.get("data") or [])
    total = max(reported_total, len(items))
    total_matches = len(items) == reported_total if has_total else has_pages
    identifiers = [item.get("numeroControlePNCP") for item in items]
    unique_identifiers = {identifier for identifier in identifiers if identifier}
    unique_records = len(unique_identifiers) == len(items)
    sample_complete = no_failures and total_matches and unique_records and (has_total or has_pages)
    return total, items, sample_complete, no_failures


async def _fetch_modality(modality: int, start: date, end: date, municipality: str | None, semaphore: asyncio.Semaphore):
    base = {
        "dataInicial": start.strftime("%Y%m%d"), "dataFinal": end.strftime("%Y%m%d"),
        "codigoModalidadeContratacao": modality, "tamanhoPagina": PAGE_SIZE,
    }
    base.update({"codigoMunicipioIbge": municipality} if municipality else {"uf": UF})

    async def page(number: int, refresh: bool = False):
        async with semaphore:
            params = {**base, "pagina": number}
            if refresh:
                await invalidate_pncp_contract_page(params)
            return await get_pncp_contracts(params)

    return await _load_all_pages(await _fetch_page_with_retries(page, 1), page)


async def collect(start: date, end: date, municipality: str | None = None, modalities=DEFAULT_MODALITIES):
    """Retorna (total_reportado, itens_do_CE, amostra_completa, consulta_sem_falhas)."""
    semaphore = asyncio.Semaphore(PAGE_CONCURRENCY)
    results = await asyncio.gather(*(_fetch_modality(m, start, end, municipality, semaphore) for m in modalities), return_exceptions=True)
    total, unique, sample_complete, no_failures = 0, {}, True, True
    for result in results:
        if isinstance(result, Exception):
            no_failures = False
            sample_complete = False
            continue
        group_total, items, complete, group_no_failures = result
        total += group_total
        sample_complete = sample_complete and complete
        no_failures = no_failures and group_no_failures
        for item in items:
            key = item.get("numeroControlePNCP")
            if key and is_ceara(item):
                unique[key] = item
    if len(unique) != total:
        sample_complete = False
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


async def fetch_open(municipality: str | None, today: date):
    base = {"dataFinal": today.strftime("%Y%m%d"), "tamanhoPagina": PAGE_SIZE}
    base.update({"codigoMunicipioIbge": municipality} if municipality else {"uf": UF})
    semaphore = asyncio.Semaphore(PAGE_CONCURRENCY)

    async def page(number: int, refresh: bool = False):
        async with semaphore:
            params = {**base, "pagina": number}
            if refresh:
                await invalidate_pncp_proposal_page(params)
            return await get_pncp_proposals(params)

    total, raw, complete, no_failures = await _load_all_pages(await _fetch_page_with_retries(page, 1), page)
    unique = {item.get("numeroControlePNCP"): item for item in raw if is_ceara(item) and item.get("numeroControlePNCP")}
    items = sorted(unique.values(), key=lambda item: str(item.get("dataEncerramentoProposta") or ""))
    if len(items) != total:
        complete = False
    return total, items, complete, no_failures
