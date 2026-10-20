import asyncio  # fila assíncrona do worker
from collections import defaultdict  # acumuladores por natureza
from datetime import datetime, timezone  # carimbos de atualização
from decimal import Decimal, InvalidOperation  # aritmética monetária exata
from hashlib import sha256  # hash de conteúdo do relatório
import json  # serialização para hash
import time  # espera entre tentativas
import requests  # extração obrigatória via requests (sem pd.read_json/read_csv)

from postgrest.exceptions import APIError

from src.config import settings
from src.db import get_db
from src.logger import logger

SOURCE_LABEL = "Portal da Transparência dos Municípios, TCE.CE.GOV.BR"
PAGE_SIZE = 1000  # tamanho de página exigido ($count)
VALID_ELEMENTS = {"39", "30", "51", "52", "32", "40", "35"}  # 5ª e 6ª posições do código do elemento
ELEMENT_NAMES = {
    "30": "MATERIAL DE CONSUMO",
    "32": "MATERIAL, BEM OU SERVIÇO PARA DISTRIBUIÇÃO GRATUITA",
    "35": "SERVIÇOS DE CONSULTORIA",
    "39": "OUTROS SERVIÇOS DE TERCEIROS - PESSOA JURÍDICA",
    "40": "SERVIÇOS DE TECNOLOGIA DA INFORMAÇÃO E COMUNICAÇÃO - PJ",
    "51": "OBRAS E INSTALAÇÕES",
    "52": "EQUIPAMENTOS E MATERIAL PERMANENTE",
}
PORTE_ME = "01"  # único código de porte considerado no recorte ME
PORTE_CODES = {"MICROEMPRESA": "01", "EMPRESA DE PEQUENO PORTE": "03", "DEMAIS": "05"}  # códigos RFB


def _table(name: str):
    db = get_db()
    return db.schema("licita_ai").table(name) if db else None


def _exercise(year: int) -> str:
    return f"{year}00"


def _month_ref(value: str | None) -> str | None:
    if not value:
        return None
    return str(value)[:7].replace("-", "")


def _digits(value: str | None) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _to_decimal(value: str | int | float | Decimal | None) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal("0")


def _porte_codigo(company: dict) -> str | None:
    explicit = str(company.get("porte_codigo") or "").strip()  # usa o código oficial quando a base o informa
    if explicit:
        return explicit.zfill(2)
    text = str(company.get("porte_empresa") or company.get("porte") or "").strip().upper()  # texto do OpenCNPJ
    if not text:
        return None  # porte não informado
    if "MICROEMPRESA" in text or "MICRO EMPRESA" in text:
        return "01"
    if "PEQUENO PORTE" in text:
        return "03"
    return "05"  # demais


def _normalize_porte(codigo: str | None) -> str:
    if not codigo:
        return "desconhecido"  # sem porte: fora do ME, mas dentro do total geral
    if codigo == PORTE_ME:
        return "micro"  # somente porte_codigo 01 compõe o subtotal ME
    if codigo == "03":
        return "pequena"
    return "demais"


def _report_hash(payload: dict | list) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(normalized.encode("utf-8")).hexdigest()


def _request_content(path: str, params: dict) -> list[dict]:
    url = f"{settings.tce_base_url.rstrip('/')}/{path}.json"  # endpoint JSON do TCE-CE
    last_error: Exception | None = None  # último erro para diagnóstico
    for attempt in range(4):  # até 4 tentativas
        try:
            response = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=120)  # requisição simples via requests
            if response.status_code == 404:
                return []  # a API responde 404 quando o filtro não tem registros
            response.raise_for_status()  # falha em 4xx/5xx
            return response.json().get("rsp", {}).get("_content") or []  # extrai o conteúdo
        except (requests.RequestException, ValueError) as error:
            last_error = error  # guarda o erro
            time.sleep(min(2 ** attempt, 6))  # espera exponencial
    raise RuntimeError(f"Falha ao consultar TCE ({path}): {last_error}")


def _record_signature(record: dict) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False)  # assinatura estável do registro


def _paginate(path: str, params: dict) -> list[dict]:
    rows: list[dict] = []  # registros acumulados
    seen_pages: set[str] = set()  # primeira assinatura de cada página
    start_index = 0  # deslocamento inicial
    while True:  # pagina até a última página
        page = _request_content(path, {**params, "$count": PAGE_SIZE, "$start_index": start_index})  # uma página
        if not page:
            break  # nada mais a ler
        signature = _record_signature(page[0])  # identifica a página
        if signature in seen_pages:
            break  # servidor ignorou $start_index e repetiu a página: evita laço infinito
        seen_pages.add(signature)  # registra a página
        rows.extend(page)  # acumula registros
        if len(page) < PAGE_SIZE:
            break  # página incompleta é a última
        start_index += PAGE_SIZE  # avança o deslocamento
    return rows


def _load_tce_municipality_map() -> dict[str, dict]:
    table = _table("tce_municipality_map")
    if table is None:
        return {}
    result = table.select("ibge_code,tce_code,municipality_name").execute().data or []
    return {row["ibge_code"]: row for row in result}


def refresh_municipality_map() -> int:
    table = _table("tce_municipality_map")
    if table is None:
        return 0
    rows = []
    for item in _request_content("municipios", {}):
        ibge = _digits(item.get("geoibgeId"))
        tce = str(item.get("codigo_municipio") or "").strip()
        name = str(item.get("nome_municipio") or "").strip()
        if len(ibge) == 7 and tce and name:
            rows.append({
                "ibge_code": ibge,
                "tce_code": tce,
                "municipality_name": name,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
    if not rows:
        return 0
    table.upsert(rows, on_conflict="ibge_code").execute()
    return len(rows)


def _resolve_tce_code(ibge_code: str) -> tuple[str, str]:
    found = _load_tce_municipality_map().get(ibge_code)  # tenta o mapa local
    if found:
        return found["tce_code"], found["municipality_name"]
    refresh_municipality_map()  # atualiza o mapa pelo TCE
    found = _load_tce_municipality_map().get(ibge_code)
    if not found:
        raise RuntimeError(f"Município IBGE não encontrado no TCE: {ibge_code}")
    return found["tce_code"], found["municipality_name"]


def _empenho_key(row: dict) -> tuple[str, ...]:
    # chave completa de 6 campos; data_referencia_doc fica de fora de propósito
    return (
        str(row.get("codigo_municipio") or "").strip(),
        str(row.get("exercicio_orcamento") or "").strip(),
        str(row.get("codigo_orgao") or "").strip(),
        str(row.get("codigo_unidade_orcamentaria") or row.get("codigo_unidade") or "").strip(),
        str(row.get("data_emissao_empenho") or "")[:10],
        str(row.get("numero_empenho") or "").strip(),
    )


def _fetch_open_cnpj(cnpj: str) -> dict | None:
    url = f"{settings.open_cnpj_base_url.rstrip('/')}/{cnpj}"  # base de CNPJs (Receita Federal)
    for attempt in range(3):  # até 3 tentativas
        try:
            response = requests.get(url, timeout=30)  # consulta pelo CNPJ normalizado
            if response.status_code == 404:
                return {}  # CNPJ inexistente na base: porte não informado
            if response.status_code == 429:
                time.sleep(5 * (attempt + 1))  # respeita limite de taxa
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            time.sleep(2 ** attempt)  # espera antes de repetir
    return None  # falha transitória: não grava no cache


def _load_cached_supplier_profiles(cnpjs: set[str]) -> dict[str, str]:
    table = _table("tce_supplier_profiles")
    if table is None or not cnpjs:
        return {}
    mapped = {}
    values = sorted(cnpjs)
    for offset in range(0, len(values), 250):
        rows = table.select("cnpj,porte_raw").in_("cnpj", values[offset:offset + 250]).execute().data or []
        # reclassifica a partir do porte bruto para não depender de regras antigas
        mapped.update({row["cnpj"]: _normalize_porte(_porte_codigo({"porte_empresa": row.get("porte_raw") if row.get("porte_raw") != "N/I" else ""})) for row in rows})
    return mapped


def _classify_missing_cnpjs(cnpjs: set[str]) -> dict[str, str]:
    table = _table("tce_supplier_profiles")
    if table is None or not cnpjs:
        return {}
    known = _load_cached_supplier_profiles(cnpjs)
    missing = sorted(cnpjs - set(known))
    inserted = []
    for cnpj in missing:
        company = _fetch_open_cnpj(cnpj)
        if company is None:
            logger.warning("Falha ao consultar OpenCNPJ %s; porte ficará sem cache", cnpj)
            known[cnpj] = "desconhecido"
            continue
        porte_raw = company.get("porte_empresa") or company.get("porte")
        group = _normalize_porte(_porte_codigo(company))
        inserted.append({
            "cnpj": cnpj,
            "company_name": company.get("razao_social"),
            "porte_raw": porte_raw or "N/I",
            "porte_group": group,
            "source": "open_cnpj",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
        known[cnpj] = group
        if len(inserted) >= 200:
            table.upsert(inserted, on_conflict="cnpj").execute()  # grava em lotes
            inserted = []
    if inserted:
        table.upsert(inserted, on_conflict="cnpj").execute()
    return known


def enqueue_sync_request(ibge_code: str, year: int) -> bool:
    table = _table("tce_sync_requests")
    if table is None:
        return False
    now = datetime.now(timezone.utc).isoformat()
    try:
        table.upsert({
            "municipality_ibge_code": ibge_code,
            "year": year,
            "status": "pending",
            "attempts": 0,
            "next_attempt_at": now,
            "last_error": None,
            "updated_at": now,
        }, on_conflict="municipality_ibge_code,year").execute()
        return True
    except APIError as error:
        logger.warning("Falha ao enfileirar sincronização TCE %s/%s: %s", ibge_code, year, error)
        return False


def claim_sync_requests(batch_size: int = 1) -> list[dict]:
    db = get_db()
    if db is None:
        return []
    try:
        result = db.schema("licita_ai").rpc("claim_tce_sync_requests", {"batch_size": batch_size}).execute()
        return result.data or []
    except APIError as error:
        logger.warning("Falha ao reservar fila de sincronização TCE: %s", error)
        return []


def mark_sync_failed(ibge_code: str, year: int, message: str, attempts: int) -> None:
    table = _table("tce_sync_requests")
    if table is None:
        return
    now = datetime.now(timezone.utc)
    retry = now.timestamp() + min(120 * (2 ** attempts), 3600)
    status = "failed"
    table.update({
        "status": status,
        "attempts": attempts,
        "next_attempt_at": datetime.fromtimestamp(retry, tz=timezone.utc).isoformat(),
        "last_error": message[:500],
        "updated_at": now.isoformat(),
    }).eq("municipality_ibge_code", ibge_code).eq("year", year).execute()


def mark_sync_complete(ibge_code: str, year: int) -> None:
    table = _table("tce_sync_requests")
    if table is None:
        return
    table.update({
        "status": "complete",
        "last_error": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("municipality_ibge_code", ibge_code).eq("year", year).execute()


def load_municipality_report(ibge_code: str, year: int) -> dict | None:
    summary_table = _table("tce_expense_municipality_year")
    detail_table = _table("tce_expense_nature_year")
    if summary_table is None or detail_table is None:
        return None
    summary_result = summary_table.select("*").eq("municipality_ibge_code", ibge_code).eq("year", year).limit(1).execute().data or []
    if not summary_result:
        return None
    summary = summary_result[0]
    details = detail_table.select("*").eq("municipality_ibge_code", ibge_code).eq("year", year).order("nature_name").execute().data or []
    return {"summary": summary, "details": details}


def list_year_reports(year: int) -> list[dict]:
    table = _table("tce_expense_municipality_year")
    if table is None:
        return []
    rows = table.select("*").eq("year", year).order("municipality_name").execute().data or []
    return rows


def get_sync_request(ibge_code: str, year: int) -> dict | None:
    table = _table("tce_sync_requests")
    if table is None:
        return None
    rows = table.select("*").eq("municipality_ibge_code", ibge_code).eq("year", year).limit(1).execute().data or []
    return rows[0] if rows else None


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def select_orgaos(orgaos: list[dict]) -> list[str]:
    # exclui a Câmara Municipal identificada dinamicamente pelo nome; mantém Prefeitura e secretarias
    selected = []  # códigos aceitos
    for item in orgaos:
        code = str(item.get("codigo_orgao") or "").strip()  # código do órgão
        name = str(item.get("nome_orgao") or "").upper()  # nome para identificar a Câmara
        if not code or "CAMARA" in name.replace("Â", "A").replace("�", "A"):
            continue  # ignora vazio e Câmara
        selected.append(code)
    return sorted(set(selected))


def aggregate_payments(empenhos: list[dict], pagamentos: list[dict]) -> dict:
    empenho_by_key: dict[tuple, dict] = {}  # empenho único por chave de 6 campos
    for note in empenhos:
        empenho_by_key.setdefault(_empenho_key(note), note)  # mantém o primeiro registro
    seen_notes: set[tuple] = set()  # notas de pagamento já somadas
    by_element: dict[str, dict] = {}  # totais por elemento de despesa
    matched = unmatched = 0  # contadores de cruzamento
    for pay in pagamentos:
        if str(pay.get("estado_de_estornado") or "").strip() != "0":
            continue  # somente pagamentos não estornados
        key = _empenho_key(pay)  # chave completa de 6 campos
        note = empenho_by_key.get(key)  # empenho vinculado
        if note is None:
            unmatched += 1  # pagamento de órgão excluído ou sem empenho
            continue
        element = str(note.get("codigo_elemento_despesa") or "").strip()[4:6]  # 5ª e 6ª posições
        if element not in VALID_ELEMENTS:
            continue  # elemento fora das 7 naturezas
        note_id = key + (
            str(pay.get("numero_sub_empenho") or "").strip(),
            str(pay.get("numero_nota_pagamento") or "").strip(),
            str(pay.get("data_nota_pagamento") or "")[:10],
            str(pay.get("valor_nota_pagamento") or "").strip(),
        )  # identificador único da nota de pagamento
        if note_id in seen_notes:
            continue  # soma cada nota uma única vez
        seen_notes.add(note_id)  # marca como somada
        matched += 1  # cruzamento válido
        amount = _to_decimal(pay.get("valor_nota_pagamento"))  # valor da nota
        entry = by_element.setdefault(element, {"total": Decimal("0"), "cnpjs": defaultdict(Decimal)})  # acumulador
        entry["total"] += amount  # total da natureza
        cnpj = _digits(note.get("numero_documento_negociante"))  # CNPJ normalizado (sem pontuação)
        entry["cnpjs"][cnpj if len(cnpj) == 14 else ""] += amount  # valor por fornecedor
    return {"by_element": by_element, "matched": matched, "unmatched": unmatched}


def collect_municipality_data(tce_code: str, year: int) -> tuple[list[dict], list[dict]]:
    base = {"codigo_municipio": tce_code, "exercicio_orcamento": _exercise(year)}  # filtros comuns
    orgaos = select_orgaos(_request_content("orgaos", base))  # órgãos sem a Câmara
    if not orgaos:
        raise RuntimeError(f"TCE não retornou órgãos para município {tce_code}/{year}")
    empenhos: list[dict] = []  # empenhos coletados
    for orgao in orgaos:  # a API exige o órgão no endpoint de empenhos
        for month in range(1, 13):  # 202501 a 202512
            empenhos.extend(_paginate("notas_empenhos", {**base, "codigo_orgao": orgao, "data_referencia_empenho": f"{year}{month:02d}"}))
    pagamentos: list[dict] = []  # pagamentos coletados
    refs = [f"{year}{month:02d}" for month in range(1, 13)] + [f"{year + 1}{month:02d}" for month in range(1, 10)]  # 202501 a 202609
    for ref in refs:
        pagamentos.extend(_paginate("notas_pagamentos", {**base, "data_referencia": ref}))
    allowed = set(orgaos)  # órgãos válidos
    return empenhos, [pay for pay in pagamentos if str(pay.get("codigo_orgao") or "").strip() in allowed]


def sync_municipality_year(ibge_code: str, year: int) -> dict:
    tce_code, municipality_name = _resolve_tce_code(ibge_code)  # código TCE do município
    empenhos, pagamentos = collect_municipality_data(tce_code, year)  # coleta paginada via requests
    aggregated = aggregate_payments(empenhos, pagamentos)  # cruzamento e filtros financeiros
    by_nature = aggregated["by_element"]
    matched, unmatched = aggregated["matched"], aggregated["unmatched"]
    cnpjs = {cnpj for entry in by_nature.values() for cnpj in entry["cnpjs"] if cnpj}  # fornecedores distintos
    profile_map = _classify_missing_cnpjs(cnpjs)  # porte por CNPJ
    detail_rows = []
    micro_total = Decimal("0")
    pequena_total = Decimal("0")
    demais_total = Decimal("0")
    unknown_total = Decimal("0")
    for code in sorted(by_nature):
        entry = by_nature[code]
        total_amount = entry["total"]
        micro = pequena = demais = unknown = Decimal("0")
        for cnpj, amount in entry["cnpjs"].items():
            group = profile_map.get(cnpj, "desconhecido") if cnpj else "desconhecido"  # sem CNPJ válido: sem porte
            if group == "micro":
                micro += amount
            elif group == "pequena":
                pequena += amount
            elif group == "demais":
                demais += amount
            else:
                unknown += amount
        mpe = micro  # recorte ME: somente porte_codigo 01
        micro_total += micro
        pequena_total += pequena
        demais_total += demais
        unknown_total += unknown
        detail_payload = {
            "municipality_ibge_code": ibge_code,
            "year": year,
            "nature_code": code,
            "nature_name": ELEMENT_NAMES[code],
            "total_amount": float(_round_money(total_amount)),
            "micro_amount": float(_round_money(micro)),
            "pequena_amount": float(_round_money(pequena)),
            "demais_amount": float(_round_money(demais)),
            "unknown_amount": float(_round_money(unknown)),
            "mpe_amount": float(_round_money(mpe)),
            "mpe_percent": float((mpe / total_amount) if total_amount > 0 else 0),
        }
        detail_payload["content_hash"] = _report_hash(detail_payload)
        detail_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        detail_rows.append(detail_payload)

    total_amount = micro_total + pequena_total + demais_total + unknown_total
    summary_payload = {
        "municipality_ibge_code": ibge_code,
        "year": year,
        "municipality_name": municipality_name,
        "total_amount": float(_round_money(total_amount)),
        "micro_amount": float(_round_money(micro_total)),
        "pequena_amount": float(_round_money(pequena_total)),
        "demais_amount": float(_round_money(demais_total)),
        "unknown_amount": float(_round_money(unknown_total)),
        "mpe_amount": float(_round_money(micro_total)),
        "mpe_percent": float((micro_total / total_amount) if total_amount > 0 else 0),
        "matched_liquidations": matched,
        "unmatched_liquidations": unmatched,
        "source_label": SOURCE_LABEL,
    }
    summary_payload["content_hash"] = _report_hash(summary_payload | {"details": detail_rows})
    summary_payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    summary_table = _table("tce_expense_municipality_year")
    detail_table = _table("tce_expense_nature_year")
    if summary_table is None or detail_table is None:
        raise RuntimeError("Supabase indisponível para persistir relatório TCE")
    summary_table.upsert(summary_payload, on_conflict="municipality_ibge_code,year").execute()
    if detail_rows:
        detail_table.delete().eq("municipality_ibge_code", ibge_code).eq("year", year).execute()
        detail_table.upsert(detail_rows, on_conflict="municipality_ibge_code,year,nature_code").execute()
    return {"summary": summary_payload, "details": detail_rows}


async def process_sync_queue(batch_size: int = 1) -> dict:
    jobs = await asyncio.to_thread(claim_sync_requests, batch_size)
    if not jobs:
        return {"status": "idle", "processed": 0}
    processed = 0
    for job in jobs:
        ibge_code = str(job.get("municipality_ibge_code") or "")
        year = int(job.get("year") or 0)
        attempts = int(job.get("attempts") or 0) + 1
        try:
            await asyncio.to_thread(sync_municipality_year, ibge_code, year)  # coleta bloqueante fora do loop de eventos
            await asyncio.to_thread(mark_sync_complete, ibge_code, year)
            processed += 1
        except Exception as error:
            logger.exception("Falha ao sincronizar compras TCE %s/%s", ibge_code, year)
            await asyncio.to_thread(mark_sync_failed, ibge_code, year, str(error), attempts)
    return {"status": "ok", "processed": processed}
