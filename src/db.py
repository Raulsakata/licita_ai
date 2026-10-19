from collections import deque
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from postgrest import CountMethod
from postgrest.exceptions import APIError
from supabase import create_client, Client
from src.config import settings
from src.logger import logger
from src.transform import opportunity_content_hash


@lru_cache
def get_db() -> Client | None:
    secret_key = settings.supabase_secret_key or settings.supabase_service_role_key
    if not settings.supabase_url or not secret_key:
        return None
    return create_client(settings.supabase_url, secret_key)


def save_company(company: dict, eligibility: dict) -> None:
    db = get_db()
    if not db:
        return
    try:
        db.schema("licita_ai").table("companies").upsert(company, on_conflict="cnpj").execute()
        db.schema("licita_ai").table("eligibility_assessments").insert({
            "cnpj": eligibility["cnpj"],
            "micro_ou_pequena": eligibility["micro_ou_pequena"],
            "apta_indicativamente": eligibility["apta_indicativamente"],
            "motivo": eligibility["motivo"],
        }).execute()
    except APIError as error:
        logger.warning("Falha ao salvar empresa/avaliacao no Supabase: %s", error)


def save_pncp_results(payload: dict, municipality_code: str | None = None) -> bool:
    db = get_db()
    if not db:
        return False
    from src.transform import normalize_opportunity
    rows = [row for item in payload.get("data", []) if (row := normalize_opportunity(item, municipality_code))]
    if not rows:
        return True
    try:
        table = db.schema("licita_ai").table("pncp_opportunities")
        changed_rows = []
        for offset in range(0, len(rows), 250):
            batch = rows[offset:offset + 250]
            ids = [row["pncp_id"] for row in batch]
            existing = table.select("pncp_id,content_hash,html_data").in_("pncp_id", ids).execute().data or []
            existing_by_id = {row["pncp_id"]: row for row in existing}
            for row in batch:
                previous = existing_by_id.get(row["pncp_id"], {})
                html_data = previous.get("html_data") or {}
                raw_data = row["raw_data"]
                content_hash = opportunity_content_hash(raw_data, html_data)
                if previous.get("content_hash") == content_hash:
                    continue
                row.update({
                    "html_data": html_data,
                    "content_hash": content_hash,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                changed_rows.append(row)
        for offset in range(0, len(changed_rows), 250):
            table.upsert(changed_rows[offset:offset + 250], on_conflict="pncp_id").execute()
        return True
    except APIError as error:
        logger.warning("Falha ao salvar oportunidades PNCP no Supabase: %s", error)
        return False


def get_geographic_reference(reference_key: str) -> dict | None:
    """Carrega do Supabase uma referência geográfica sincronizada pelo worker."""
    table = _table("geographic_reference")
    if table is None:
        return None
    try:
        result = table.select("payload,fetched_at").eq("reference_key", reference_key).limit(1).execute()
        return result.data[0] if result.data else None
    except APIError as error:
        logger.warning("Falha ao carregar referência geográfica %s: %s", reference_key, error)
        return None


def save_geographic_reference(reference_key: str, payload: dict | list) -> bool:
    """Persiste as referências IBGE para que o painel público não dependa do IBGE em tempo real."""
    table = _table("geographic_reference")
    if table is None:
        return False
    try:
        table.upsert({
            "reference_key": reference_key,
            "payload": payload,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="reference_key").execute()
        return True
    except APIError as error:
        logger.warning("Falha ao persistir referência geográfica %s: %s", reference_key, error)
        return False


def list_saved_searches() -> list[dict]:
    db = get_db()
    if not db:
        return []
    try:
        result = db.schema("licita_ai").table("saved_searches").select("*").order("created_at", desc=True).execute()
        return result.data or []
    except APIError as error:
        logger.warning("Falha ao listar consultas salvas no Supabase: %s", error)
        return []


def create_saved_search(name: str, filters: dict) -> dict | None:
    db = get_db()
    if not db:
        return None
    try:
        result = db.schema("licita_ai").table("saved_searches").insert({"name": name, "filters": filters}).execute()
        return result.data[0] if result.data else None
    except APIError as error:
        logger.warning("Falha ao criar consulta salva no Supabase: %s", error)
        return None


def delete_saved_search(search_id: str) -> None:
    db = get_db()
    if not db:
        return
    try:
        db.schema("licita_ai").table("saved_searches").delete().eq("id", search_id).execute()
    except APIError as error:
        logger.warning("Falha ao remover consulta salva no Supabase: %s", error)


COMPANY_PUBLIC_COLUMNS = "cnpj,razao_social,nome_fantasia,porte,situacao_cadastral,natureza_juridica,natureza_juridica_codigo,ativo,last_login_at,updated_at"
SYSTEM_LOGS: deque = deque(maxlen=500)


def _table(name: str):
    db = get_db()
    return db.schema("licita_ai").table(name) if db else None


def get_company(cnpj: str) -> dict | None:
    table = _table("companies")
    if table is None:
        return None
    try:
        result = table.select("*").eq("cnpj", cnpj).limit(1).execute()
        return result.data[0] if result.data else None
    except APIError as error:
        logger.warning("Falha ao buscar empresa no Supabase: %s", error)
        return None


def list_companies() -> list[dict]:
    table = _table("companies")
    if table is None:
        return []
    try:
        return table.select(COMPANY_PUBLIC_COLUMNS).order("updated_at", desc=True).limit(1000).execute().data or []
    except APIError as error:
        logger.warning("Falha ao listar empresas no Supabase: %s", error)
        return []


def upsert_company_fields(fields: dict) -> dict | None:
    table = _table("companies")
    if table is None:
        return None
    try:
        result = table.upsert(fields, on_conflict="cnpj").execute()
        return result.data[0] if result.data else None
    except APIError as error:
        logger.warning("Falha ao gravar empresa no Supabase: %s", error)
        return None


def update_company(cnpj: str, fields: dict) -> dict | None:
    table = _table("companies")
    if table is None:
        return None
    try:
        result = table.update(fields).eq("cnpj", cnpj).execute()
        return result.data[0] if result.data else None
    except APIError as error:
        logger.warning("Falha ao atualizar empresa no Supabase: %s", error)
        return None


def delete_company(cnpj: str) -> bool:
    db = get_db()
    if not db:
        return False
    try:
        db.schema("licita_ai").table("eligibility_assessments").delete().eq("cnpj", cnpj).execute()
        db.schema("licita_ai").table("companies").delete().eq("cnpj", cnpj).execute()
        return True
    except APIError as error:
        logger.warning("Falha ao remover empresa no Supabase: %s", error)
        return False


def count_rows(table_name: str) -> int | None:
    table = _table(table_name)
    if table is None:
        return None
    try:
        return table.select("*", count=CountMethod.exact).limit(1).execute().count
    except APIError as error:
        logger.warning("Falha ao contar %s no Supabase: %s", table_name, error)
        return None


def log_event(event: str, actor: str = "sistema", level: str = "info", detail: dict | None = None) -> None:
    entry = {"level": level, "event": event, "actor": actor, "detail": detail or {}, "created_at": datetime.now(timezone.utc).isoformat()}
    SYSTEM_LOGS.appendleft(entry)
    table = _table("system_logs")
    if table is None:
        return
    try:
        table.insert({key: entry[key] for key in ("level", "event", "actor", "detail")}).execute()
    except APIError as error:
        logger.warning("Falha ao gravar log no Supabase: %s", error)


def list_logs(limit: int = 200, level: str | None = None) -> list[dict]:
    table = _table("system_logs")
    if table is not None:
        try:
            query = table.select("level,event,actor,detail,created_at").order("created_at", desc=True).limit(limit)
            if level:
                query = query.eq("level", level)
            return query.execute().data or []
        except APIError as error:
            logger.warning("Falha ao listar logs no Supabase: %s", error)
    logs = [entry for entry in SYSTEM_LOGS if not level or entry["level"] == level]
    return logs[:limit]


def load_pncp_results(start: date, end: date, municipality_code: str | None = None) -> list[dict] | None:
    table = _table("pncp_opportunities")
    if table is None:
        return None
    try:
        rows = []
        offset = 0
        page_size = 1000
        end_exclusive = (end + timedelta(days=1)).isoformat()
        while True:
            query = table.select("pncp_id,municipality_ibge_code,uf,publication_date,raw_data,html_data")
            query = query.gte("publication_date", start.isoformat()).lt("publication_date", end_exclusive)
            query = query.eq("uf", "CE")
            if municipality_code:
                query = query.eq("municipality_ibge_code", municipality_code)
            page = query.order("publication_date").range(offset, offset + page_size - 1).execute().data or []
            from src.transform import merge_html_fields
            for row in page:
                row["raw_data"] = merge_html_fields(row.get("raw_data") or {}, row.get("html_data"))
            rows.extend(page)
            if len(page) < page_size:
                return rows
            offset += page_size
    except APIError as error:
        logger.warning("Falha ao carregar oportunidades PNCP do Supabase: %s", error)
        return None


def list_pncp_sync_windows(modalities: list[int]) -> list[dict] | None:
    table = _table("pncp_sync_windows")
    if table is None:
        return None
    try:
        return table.select("modality_code,starts_on,ends_on,fetched_at,total_records,stored_records").in_("modality_code", modalities).execute().data or []
    except APIError as error:
        logger.warning("Falha ao consultar janelas de sincronização PNCP: %s", error)
        return None


def save_pncp_sync_window(modality: int, start: date, end: date, total: int, stored: int) -> bool:
    table = _table("pncp_sync_windows")
    if table is None:
        return False
    try:
        table.upsert({
            "modality_code": modality, "starts_on": start.isoformat(), "ends_on": end.isoformat(),
            "total_records": total, "stored_records": stored, "fetched_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="modality_code,starts_on,ends_on").execute()
        return True
    except APIError as error:
        logger.warning("Falha ao gravar janela de sincronização PNCP: %s", error)
        return False


def get_pncp_sync_state() -> dict | None:
    table = _table("pncp_sync_state")
    if table is None:
        return None
    try:
        result = table.select("status,last_started_at,last_completed_at,last_error,updated_at").eq("singleton", True).limit(1).execute()
        return result.data[0] if result.data else None
    except APIError as error:
        logger.warning("Falha ao consultar estado do sincronizador PNCP: %s", error)
        return None


def update_pncp_sync_state(status: str, started_at: str | None = None, completed_at: str | None = None, error: str | None = None) -> bool:
    table = _table("pncp_sync_state")
    if table is None:
        return False
    try:
        existing = get_pncp_sync_state() or {}
        table.upsert({
            "singleton": True,
            "status": status,
            "last_started_at": started_at or existing.get("last_started_at"),
            "last_completed_at": completed_at or existing.get("last_completed_at"),
            "last_error": error[:500] if error else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="singleton").execute()
        return True
    except APIError as error:
        logger.warning("Falha ao atualizar estado do sincronizador PNCP: %s", error)
        return False


def save_pncp_open_snapshot(items: list[dict]) -> bool:
    table = _table("pncp_open_opportunities")
    if table is None:
        return False
    from src.licitacoes import is_ceara
    rows = []
    for item in items:
        if not is_ceara(item) or not item.get("numeroControlePNCP"):
            continue
        unit = item.get("unidadeOrgao") or {}
        municipality_code = unit.get("codigoIbge") or item.get("codigoMunicipioIbge")
        rows.append({
            "pncp_id": str(item["numeroControlePNCP"]),
            "municipality_ibge_code": municipality_code,
            "uf": "CE",
            "proposal_end": normalize_pncp_timestamp(item.get("dataEncerramentoProposta")),
            "raw_data": item,
        })
    try:
        existing_by_id = {}
        ids = [row["pncp_id"] for row in rows]
        for offset in range(0, len(ids), 250):
            page = table.select("pncp_id,content_hash,html_data").in_("pncp_id", ids[offset:offset + 250]).execute().data or []
            existing_by_id.update({row["pncp_id"]: row for row in page})
        changed_rows = []
        for row in rows:
            previous = existing_by_id.get(row["pncp_id"], {})
            html_data = previous.get("html_data") or {}
            content_hash = opportunity_content_hash(row["raw_data"], html_data)
            if previous.get("content_hash") == content_hash:
                continue
            row.update({
                "html_data": html_data,
                "content_hash": content_hash,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            changed_rows.append(row)
        for offset in range(0, len(changed_rows), 250):
            table.upsert(changed_rows[offset:offset + 250], on_conflict="pncp_id").execute()
        return True
    except APIError as error:
        logger.warning("Falha ao salvar snapshot de editais abertos no Supabase: %s", error)
        return False


def normalize_pncp_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=-3)))
    return parsed.astimezone(timezone.utc).isoformat()


def load_pncp_open_snapshot(municipality_code: str | None = None) -> list[dict] | None:
    table = _table("pncp_open_opportunities")
    if table is None:
        return None
    try:
        rows, offset, page_size = [], 0, 1000
        now = datetime.now(timezone.utc).isoformat()
        while True:
            query = table.select("pncp_id,municipality_ibge_code,proposal_end,raw_data,html_data").eq("uf", "CE").gt("proposal_end", now)
            if municipality_code:
                query = query.eq("municipality_ibge_code", municipality_code)
            page = query.order("proposal_end").range(offset, offset + page_size - 1).execute().data or []
            from src.transform import merge_html_fields
            for row in page:
                row["raw_data"] = merge_html_fields(row.get("raw_data") or {}, row.get("html_data"))
            rows.extend(page)
            if len(page) < page_size:
                return rows
            offset += page_size
    except APIError as error:
        logger.warning("Falha ao carregar snapshot de editais abertos: %s", error)
        return None


def _pncp_detail_page_url(item: dict) -> str | None:
    organ = item.get("orgaoEntidade") or {}
    cnpj = "".join(character for character in str(organ.get("cnpj") or "") if character.isdigit())
    year = str(item.get("anoCompra") or "")
    sequence = str(item.get("sequencialCompra") or "")
    if len(cnpj) != 14 or not year.isdigit() or len(year) != 4 or not sequence.isdigit():
        return None
    return f"https://pncp.gov.br/app/editais/{cnpj}/{year}/{sequence}"


def enqueue_pncp_html_scrapes(items: list[dict]) -> bool:
    db = get_db()
    if not db:
        return False
    entries = []
    for item in items:
        pncp_id = str(item.get("numeroControlePNCP") or "")
        page_url = _pncp_detail_page_url(item)
        if not pncp_id or not page_url:
            logger.warning("PNCP sem dados para gerar URL de scraping; id=%s", pncp_id or "ausente")
            continue
        entries.append({
            "pncp_id": pncp_id,
            "page_url": page_url,
            "source_hash": opportunity_content_hash(item),
        })
    if not entries:
        return True

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cutoff = now - timedelta(seconds=settings.pncp_scrape_refresh_seconds)
    try:
        queue = db.schema("licita_ai").table("pncp_html_scrape_queue")
        pending = []
        for offset in range(0, len(entries), 250):
            batch = entries[offset:offset + 250]
            existing = queue.select(
                "pncp_id,source_hash,status,attempts,next_attempt_at,scraped_at",
            ).in_("pncp_id", [entry["pncp_id"] for entry in batch]).execute().data or []
            existing_by_id = {row["pncp_id"]: row for row in existing}
            for entry in batch:
                previous = existing_by_id.get(entry["pncp_id"], {})
                same_source = previous.get("source_hash") == entry["source_hash"]
                status = previous.get("status")
                if same_source and status in {"pending", "running"}:
                    continue
                if same_source and status == "complete":
                    scraped_at = previous.get("scraped_at")
                    try:
                        scraped = datetime.fromisoformat(str(scraped_at).replace("Z", "+00:00"))
                        if scraped.tzinfo is None:
                            scraped = scraped.replace(tzinfo=timezone.utc)
                        if scraped >= cutoff:
                            continue
                    except (TypeError, ValueError):
                        pass
                if same_source and status == "failed":
                    retry_at = previous.get("next_attempt_at")
                    try:
                        retry = datetime.fromisoformat(str(retry_at).replace("Z", "+00:00"))
                        if retry.tzinfo is None:
                            retry = retry.replace(tzinfo=timezone.utc)
                        if retry > now:
                            continue
                    except (TypeError, ValueError):
                        pass
                pending.append({
                    **entry,
                    "status": "pending",
                    "attempts": previous.get("attempts", 0) if same_source else 0,
                    "next_attempt_at": now_iso,
                    "last_error": None,
                    "updated_at": now_iso,
                })
        for offset in range(0, len(pending), 250):
            queue.upsert(pending[offset:offset + 250], on_conflict="pncp_id").execute()
        return True
    except APIError as error:
        logger.warning("Falha ao enfileirar páginas PNCP para scraping: %s", error)
        return False


def claim_pncp_html_scrapes(batch_size: int) -> list[dict] | None:
    db = get_db()
    if not db:
        return None
    try:
        result = db.schema("licita_ai").rpc(
            "claim_pncp_html_scrapes", {"batch_size": batch_size},
        ).execute()
        return result.data or []
    except APIError as error:
        logger.warning("Falha ao reservar páginas PNCP para scraping: %s", error)
        return None


def save_pncp_html_capture(pncp_id: str, page_url: str, html_data: dict) -> bool:
    db = get_db()
    if not db:
        return False
    captured_at = datetime.now(timezone.utc).isoformat()
    updated = False
    try:
        for table_name in ("pncp_opportunities", "pncp_open_opportunities"):
            table = db.schema("licita_ai").table(table_name)
            result = table.select("raw_data").eq("pncp_id", pncp_id).limit(1).execute()
            records = result.data or []
            if not records:
                continue
            raw_data = records[0].get("raw_data") or {}
            table.update({
                "html_data": html_data,
                "content_hash": opportunity_content_hash(raw_data, html_data),
                "source_url": page_url,
                "scraped_at": captured_at,
                "updated_at": captured_at,
            }).eq("pncp_id", pncp_id).execute()
            updated = True
        return updated
    except APIError as error:
        logger.warning("Falha ao persistir captura HTML do PNCP id=%s: %s", pncp_id, error)
        return False


def mark_pncp_html_scrape_complete(pncp_id: str) -> bool:
    table = _table("pncp_html_scrape_queue")
    if table is None:
        return False
    now = datetime.now(timezone.utc).isoformat()
    try:
        table.update({
            "status": "complete",
            "scraped_at": now,
            "last_error": None,
            "updated_at": now,
        }).eq("pncp_id", pncp_id).execute()
        return True
    except APIError as error:
        logger.warning("Falha ao concluir captura HTML do PNCP id=%s: %s", pncp_id, error)
        return False


def mark_pncp_html_scrape_failed(job: dict, error_message: str) -> bool:
    table = _table("pncp_html_scrape_queue")
    if table is None:
        return False
    attempts = int(job.get("attempts") or 0) + 1
    now = datetime.now(timezone.utc)
    status = "failed" if attempts < 5 else "dead"
    retry_at = now + timedelta(seconds=min(60 * (2 ** attempts), 3600))
    try:
        table.update({
            "status": status,
            "attempts": attempts,
            "next_attempt_at": retry_at.isoformat(),
            "last_error": error_message[:300],
            "updated_at": now.isoformat(),
        }).eq("pncp_id", job["pncp_id"]).execute()
        return True
    except APIError as error:
        logger.warning("Falha ao registrar erro de scraping PNCP id=%s: %s", job.get("pncp_id"), error)
        return False


def get_pncp_open_sync_state() -> dict | None:
    table = _table("pncp_open_sync_state")
    if table is None:
        return None
    try:
        result = table.select("status,last_started_at,last_completed_at,total_records,last_error,updated_at").eq("singleton", True).limit(1).execute()
        return result.data[0] if result.data else None
    except APIError as error:
        logger.warning("Falha ao consultar estado de editais abertos: %s", error)
        return None


def update_pncp_open_sync_state(status: str, started_at: str | None = None, completed_at: str | None = None, total_records: int | None = None, error: str | None = None) -> bool:
    table = _table("pncp_open_sync_state")
    if table is None:
        return False
    try:
        existing = get_pncp_open_sync_state() or {}
        table.upsert({
            "singleton": True,
            "status": status,
            "last_started_at": started_at or existing.get("last_started_at"),
            "last_completed_at": completed_at or existing.get("last_completed_at"),
            "total_records": total_records if total_records is not None else existing.get("total_records", 0),
            "last_error": error[:500] if error else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="singleton").execute()
        return True
    except APIError as error:
        logger.warning("Falha ao atualizar estado de editais abertos: %s", error)
        return False


def list_media_images(kind: str) -> list[dict]:
    table = _table("media_images")
    if table is None:
        return []
    try:
        return table.select("key,title,credit").eq("kind", kind).order("key").execute().data or []
    except APIError as error:
        logger.warning("Falha ao listar imagens: %s", error)
        return []


def get_media_image(key: str) -> dict | None:
    table = _table("media_images")
    if table is None:
        return None
    try:
        result = table.select("content_type,data_b64").eq("key", key).limit(1).execute()
        return result.data[0] if result.data else None
    except APIError as error:
        logger.warning("Falha ao carregar imagem %s: %s", key, error)
        return None
