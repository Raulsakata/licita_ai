from collections import deque
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from postgrest import CountMethod
from postgrest.exceptions import APIError
from supabase import create_client, Client
from src.config import settings
from src.logger import logger


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
        for offset in range(0, len(rows), 250):
            table.upsert(rows[offset:offset + 250], on_conflict="pncp_id", ignore_duplicates=True).execute()
        return True
    except APIError as error:
        logger.warning("Falha ao salvar oportunidades PNCP no Supabase: %s", error)
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
            query = table.select("pncp_id,municipality_ibge_code,uf,publication_date,raw_data")
            query = query.gte("publication_date", start.isoformat()).lt("publication_date", end_exclusive)
            query = query.eq("uf", "CE")
            if municipality_code:
                query = query.eq("municipality_ibge_code", municipality_code)
            page = query.order("publication_date").range(offset, offset + page_size - 1).execute().data or []
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
        for offset in range(0, len(rows), 250):
            table.upsert(rows[offset:offset + 250], on_conflict="pncp_id", ignore_duplicates=True).execute()
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
            query = table.select("pncp_id,municipality_ibge_code,proposal_end,raw_data").eq("uf", "CE").gt("proposal_end", now)
            if municipality_code:
                query = query.eq("municipality_ibge_code", municipality_code)
            page = query.order("proposal_end").range(offset, offset + page_size - 1).execute().data or []
            rows.extend(page)
            if len(page) < page_size:
                return rows
            offset += page_size
    except APIError as error:
        logger.warning("Falha ao carregar snapshot de editais abertos: %s", error)
        return None


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
