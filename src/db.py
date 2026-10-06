from collections import deque
from datetime import datetime, timezone
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


def save_pncp_results(payload: dict, municipality_code: str | None = None) -> None:
    db = get_db()
    if not db:
        return
    from src.transform import normalize_opportunity
    rows = [row for item in payload.get("data", []) if (row := normalize_opportunity(item, municipality_code))]
    if not rows:
        return
    try:
        db.schema("licita_ai").table("pncp_opportunities").upsert(rows, on_conflict="pncp_id").execute()
    except APIError as error:
        logger.warning("Falha ao salvar oportunidades PNCP no Supabase: %s", error)


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
