from functools import lru_cache
from supabase import create_client, Client
from src.config import settings


@lru_cache
def get_db() -> Client | None:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def save_company(company: dict, eligibility: dict) -> None:
    db = get_db()
    if not db:
        return
    db.schema("licita_ai").table("companies").upsert(company, on_conflict="cnpj").execute()
    db.schema("licita_ai").table("eligibility_assessments").insert({
        "cnpj": eligibility["cnpj"],
        "micro_ou_pequena": eligibility["micro_ou_pequena"],
        "apta_indicativamente": eligibility["apta_indicativamente"],
        "motivo": eligibility["motivo"],
    }).execute()


def save_pncp_results(payload: dict, municipality_code: str | None = None) -> None:
    db = get_db()
    if not db:
        return
    from src.transform import normalize_opportunity
    rows = [row for item in payload.get("data", []) if (row := normalize_opportunity(item, municipality_code))]
    if rows:
        db.schema("licita_ai").table("pncp_opportunities").upsert(rows, on_conflict="pncp_id").execute()
