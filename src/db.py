from functools import lru_cache
from postgrest.exceptions import APIError
from supabase import create_client, Client
from src.config import settings
from src.logger import logger


@lru_cache
def get_db() -> Client | None:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


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
