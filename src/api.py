import asyncio
from datetime import date, datetime, timedelta, timezone
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
from src import auth, cnae, licitacoes
from src.config import settings
from src.db import (
    COMPANY_PUBLIC_COLUMNS, count_rows, create_saved_search, delete_company, delete_saved_search, get_company, get_db,
    list_companies, list_logs, list_saved_searches, log_event, save_company, save_pncp_results, update_company,
    upsert_company_fields,
)
from src.domain import PNCP_MODALIDADES
from src.extract import get_ibge_state_mesh, get_ibge_state_municipalities, get_open_cnpj
from src.mappers import normalize_company
from src.schemas import AdminLogin, CompanyCreate, CompanyLogin, CompanyUpdate, SavedSearchCreate
from src.transform import assess_eligibility
from src.validators import validate_cnpj

MODALIDADE_CODES = {item["codigo"] for item in PNCP_MODALIDADES}
PUBLIC_COMPANY_KEYS = COMPANY_PUBLIC_COLUMNS.split(",")
MAX_OPEN_PAGES = 10

app = FastAPI(title="Licita AI API", version="0.3.0")
app.add_middleware(
    CORSMiddleware, allow_origins=[origin.strip() for origin in settings.frontend_origin.split(",")],
    allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"],
)


def resolve_period(inicio: str | None, fim: str | None) -> tuple[date, date]:
    try:
        end = licitacoes.parse_date(fim) if fim else date.today()
        start = licitacoes.parse_date(inicio) if inicio else end - timedelta(days=30)
    except ValueError as error:
        raise HTTPException(400, "As datas devem estar no formato AAAA-MM-DD") from error
    if start > end:
        raise HTTPException(400, "A data inicial deve ser anterior à final")
    if (end - start).days > licitacoes.MAX_PERIOD_DAYS:
        raise HTTPException(400, f"O período máximo é de {licitacoes.MAX_PERIOD_DAYS} dias")
    return start, end


def resolve_municipality(code: str | None) -> str | None:
    if not code:
        return None
    if not code.isdigit() or len(code) != 7 or not code.startswith(licitacoes.IBGE_UF_CODE):
        raise HTTPException(400, "A busca está disponível apenas para municípios do Ceará")
    return code


def resolve_modality(code: int | None) -> tuple[int, ...]:
    if code is None:
        return licitacoes.DEFAULT_MODALITIES
    if code not in MODALIDADE_CODES:
        raise HTTPException(400, "Código de modalidade de contratação inválido")
    return (code,)


def public_company(row: dict) -> dict:
    return {key: row.get(key) for key in PUBLIC_COMPANY_KEYS}


@app.get("/health")
def health():
    return {"status": "ok", "integrations": {"pncp": "configured", "open_cnpj": "configured", "supabase": "configured" if get_db() else "pending"}}


@app.get("/api/pncp/modalidades")
def pncp_modalidades():
    return PNCP_MODALIDADES


@app.get("/api/consultas-salvas")
def saved_searches_list(_: dict = Depends(auth.require_admin)):
    return list_saved_searches()


@app.post("/api/consultas-salvas", status_code=201)
def saved_searches_create(body: SavedSearchCreate, _: dict = Depends(auth.require_admin)):
    created = create_saved_search(body.name, body.filters)
    if created is None:
        raise HTTPException(503, "Supabase não configurado")
    return created


@app.delete("/api/consultas-salvas/{search_id}", status_code=204)
def saved_searches_delete(search_id: str, _: dict = Depends(auth.require_admin)):
    delete_saved_search(search_id)


# ---------- Geografia (somente Ceará) ----------

@app.get("/api/geografia/municipios")
async def ceara_municipalities():
    try:
        return await get_ibge_state_municipalities(int(licitacoes.IBGE_UF_CODE))
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o IBGE") from error


@app.get("/api/geografia/mapa")
async def ceara_map():
    try:
        return await get_ibge_state_mesh(int(licitacoes.IBGE_UF_CODE))
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o IBGE") from error


# ---------- Perfil 1: público ----------

async def build_summary(start: date, end: date, municipality: str | None, modalities=licitacoes.DEFAULT_MODALITIES, persist: bool = True, only_mpe: bool = False) -> dict:
    total, items, sample_complete, no_failures = await licitacoes.collect(start, end, municipality, modalities)
    if persist and items:
        await asyncio.to_thread(save_pncp_results, {"data": items}, municipality)
    shown = [item for item in items if licitacoes.has_me_epp_signal(item)] if only_mpe else items
    return {
        **licitacoes.summarize(shown, len(shown) if only_mpe else total),
        "mpe_mensal": licitacoes.closed_mpe_by_month(items),
        "somente_mpe": only_mpe,
        "uf": licitacoes.UF, "municipio": municipality,
        "data_inicial": start.isoformat(), "data_final": end.isoformat(),
        "consulta_completa": no_failures, "amostra_limitada": not sample_complete,
    }


@app.get("/api/publico/resumo")
async def public_summary(municipio: str | None = None, inicio: str | None = None, fim: str | None = None, somente_mpe: bool = False):
    start, end = resolve_period(inicio, fim)
    try:
        return await build_summary(start, end, resolve_municipality(municipio), only_mpe=somente_mpe)
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o PNCP") from error


@app.get("/api/publico/abertos")
async def public_open_notices(municipio: str | None = None, todos: bool = False, somente_mpe: bool = False):
    try:
        total, items, sample_complete, no_failures = await licitacoes.fetch_open(
            resolve_municipality(municipio), date.today(), 1000 if todos else 20, MAX_OPEN_PAGES if todos else 1,
        )
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o PNCP") from error
    if somente_mpe:
        items = [item for item in items if licitacoes.has_me_epp_signal(item)]
        total = len(items)
    return {
        "total": total, "somente_mpe": somente_mpe,
        "consulta_completa": no_failures, "amostra_limitada": not sample_complete,
        "editais": [licitacoes.shape_item(item) for item in items],
    }


@app.get("/api/publico/municipio/{codigo}/licitacoes")
async def municipality_notices(codigo: str, inicio: str | None = None, fim: str | None = None):
    municipality = resolve_municipality(codigo)
    start, end = resolve_period(inicio, fim)
    try:
        (open_total, open_items, open_complete, open_ok), (closed_total, period_items, complete, ok) = await asyncio.gather(
            licitacoes.fetch_open(municipality, date.today(), 200, MAX_OPEN_PAGES),
            licitacoes.collect(start, end, municipality, pages=3),
        )
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o PNCP") from error
    now = datetime.now().isoformat()
    open_items = [item for item in open_items if licitacoes.has_me_epp_signal(item)]
    open_ids = {item.get("numeroControlePNCP") for item in open_items}
    closed = [
        item for item in period_items
        if item.get("numeroControlePNCP") not in open_ids and licitacoes.has_me_epp_signal(item) and str(item.get("dataEncerramentoProposta") or "") < now
    ]
    closed.sort(key=lambda item: str(item.get("dataEncerramentoProposta") or ""), reverse=True)
    return {
        "municipio": municipality, "data_inicial": start.isoformat(), "data_final": end.isoformat(), "somente_mpe": True,
        "abertas_total": len(open_items), "abertas": [licitacoes.shape_item(item) for item in open_items],
        "encerradas_total": len(closed), "encerradas": [licitacoes.shape_item(item) for item in closed[:200]],
        "consulta_completa": ok and open_ok, "amostra_limitada": not complete or not open_complete,
    }


@app.get("/api/publico/comparativo-mpe")
async def mpe_comparison(municipio: str | None = None, inicio: str | None = None, fim: str | None = None, anos: int = Query(3, ge=1, le=5)):
    start, end = resolve_period(inicio, fim)
    municipality = resolve_municipality(municipio)

    async def one_year(offset: int):
        year_start, year_end = licitacoes.shift_years(start, offset), licitacoes.shift_years(end, offset)
        total, items, complete, ok = await licitacoes.collect(year_start, year_end, municipality, pages=2)
        closed = [item for item in items if licitacoes.is_closed(item)]
        mpe_items = [item for item in closed if licitacoes.has_me_epp_signal(item)]
        return {
            "ano": year_end.year, "data_inicial": year_start.isoformat(), "data_final": year_end.isoformat(),
            "quantidade_total": max(total, len(items)), "quantidade_amostra": len(items),
            "quantidade_encerradas": len(closed), "quantidade_mpe": len(mpe_items),
            "participacao_mpe": len(mpe_items) / len(closed) if closed else None,
            "valor_mpe": sum(licitacoes.item_value(item) for item in mpe_items),
            "valor_amostra": sum(licitacoes.item_value(item) for item in closed),
            "consulta_completa": ok, "amostra_limitada": not complete,
        }

    try:
        results = await asyncio.gather(*(one_year(offset) for offset in range(anos, -1, -1)))
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o PNCP") from error
    previous = None
    for row in results:
        row["variacao_quantidade_mpe"] = (row["quantidade_mpe"] - previous["quantidade_mpe"]) / previous["quantidade_mpe"] if previous and previous["quantidade_mpe"] else None
        row["variacao_valor_mpe"] = (row["valor_mpe"] - previous["valor_mpe"]) / previous["valor_mpe"] if previous and previous["valor_mpe"] else None
        previous = row
    return {"municipio": municipality, "anos": results}


# ---------- Perfil 2: empresas ----------

@app.post("/api/auth/empresa/login")
async def company_login(body: CompanyLogin):
    cnpj = validate_cnpj(body.cnpj)
    auth.ensure_not_locked(f"empresa:{cnpj}")
    if get_db() is None:
        raise HTTPException(503, "Banco de dados indisponível")
    row = get_company(cnpj)
    if not row or not row.get("ativo", True) or not auth.verify_password(body.senha, row.get("password_hash")):
        auth.register_failure(f"empresa:{cnpj}")
        log_event("login_empresa_falhou", actor=cnpj, level="warning")
        raise HTTPException(401, "CNPJ ou senha inválidos")
    auth.clear_failures(f"empresa:{cnpj}")
    try:
        company = normalize_company(await get_open_cnpj(cnpj), cnpj)
        save_company(company, assess_eligibility(company).model_dump())
        row = {**row, **{key: company[key] for key in ("razao_social", "porte", "situacao_cadastral", "natureza_juridica", "natureza_juridica_codigo")}}
    except httpx.HTTPError:
        pass
    update_company(cnpj, {"last_login_at": datetime.now(timezone.utc).isoformat()})
    log_event("login_empresa", actor=cnpj)
    eligibility = assess_eligibility(row)
    return {"token": auth.create_token(cnpj, "empresa"), "empresa": eligibility.model_dump(exclude={"oportunidades"})}


@app.get("/api/empresa/perfil")
def company_profile(actor: dict = Depends(auth.require_company)):
    row = get_company(actor["sub"])
    if not row or not row.get("ativo", True):
        raise HTTPException(401, "Sessão inválida ou expirada")
    return assess_eligibility(row).model_dump(exclude={"oportunidades"})


@app.get("/api/empresa/oportunidades")
async def company_opportunities(
    municipio: str | None = None, inicio: str | None = None, fim: str | None = None,
    modalidade: int | None = Query(None, ge=1, le=13), actor: dict = Depends(auth.require_company),
):
    row = get_company(actor["sub"])
    if not row or not row.get("ativo", True):
        raise HTTPException(401, "Sessão inválida ou expirada")
    eligibility = assess_eligibility(row)
    cnaes = cnae.company_cnaes(row.get("raw_data"), row.get("cnae_principal"))
    matcher, terms = cnae.build_matcher(cnaes)
    base = {"empresa": eligibility.model_dump(exclude={"oportunidades"}), "cnae": cnaes, "palavras_chave": terms}
    start, end = resolve_period(inicio, fim)
    if not terms:
        return {**base, "cnae_disponivel": False, "aptas": [], "nao_aptas": [], "total_nao_aptas": 0, "total_incompativeis": 0,
                "data_inicial": start.isoformat(), "data_final": end.isoformat(), "consulta_completa": True, "amostra_limitada": False}
    try:
        total, items, sample_complete, no_failures = await licitacoes.collect(
            start, end, resolve_municipality(municipio), resolve_modality(modalidade), pages=3,
        )
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o PNCP") from error
    eligible, restricted, incompatible = [], [], 0
    for item in items:
        matched = matcher(str(item.get("objetoCompra") or ""))
        if not matched:
            incompatible += 1
            continue
        shaped = {**licitacoes.shape_item(item), "cnae_termos": matched}
        if shaped["exige_porte_me_epp"] and not eligibility.apta_indicativamente:
            restricted.append({**shaped, "status": "Não Apta", "motivo": eligibility.motivo})
        else:
            eligible.append({**shaped, "status": "Apta"})
    eligible.sort(key=lambda entry: (entry["encerramento_propostas"] is None, entry["encerramento_propostas"] or ""))
    return {
        **base, "cnae_disponivel": True,
        "aptas": eligible, "nao_aptas": restricted[:50], "total_nao_aptas": len(restricted), "total_incompativeis": incompatible,
        "data_inicial": start.isoformat(), "data_final": end.isoformat(),
        "consulta_completa": no_failures, "amostra_limitada": not sample_complete,
    }


# ---------- Perfil 3: administrador ----------

@app.post("/api/auth/admin/login")
def admin_login(body: AdminLogin):
    key = f"admin:{body.usuario.lower()}"
    auth.ensure_not_locked(key)
    if not auth.check_admin_credentials(body.usuario, body.senha):
        auth.register_failure(key)
        log_event("login_admin_falhou", actor=body.usuario, level="warning")
        raise HTTPException(401, "Usuário ou senha inválidos")
    auth.clear_failures(key)
    log_event("login_admin", actor=body.usuario)
    return {"token": auth.create_token(body.usuario, "admin"), "usuario": body.usuario}


@app.get("/api/admin/painel")
def admin_dashboard(_: dict = Depends(auth.require_admin)):
    companies = list_companies()
    logs = list_logs(500)
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = [entry for entry in logs if str(entry["created_at"]) >= since]
    eligibilities = [assess_eligibility(row) for row in companies]
    return {
        "empresas_total": len(companies),
        "empresas_ativas": sum(1 for row in companies if row.get("ativo", True)),
        "empresas_aptas": sum(1 for item in eligibilities if item.apta_indicativamente),
        "empresas_nao_aptas": sum(1 for item in eligibilities if not item.apta_indicativamente),
        "logins_24h": sum(1 for entry in recent if entry["event"] == "login_empresa"),
        "alertas_24h": sum(1 for entry in recent if entry["level"] != "info"),
        "oportunidades_armazenadas": count_rows("pncp_opportunities"),
        "supabase": "configured" if get_db() else "pending",
    }


@app.get("/api/admin/fluxo")
async def admin_flow(municipio: str | None = None, inicio: str | None = None, fim: str | None = None, _: dict = Depends(auth.require_admin)):
    start, end = resolve_period(inicio, fim)
    municipality = resolve_municipality(municipio)
    try:
        total, items, sample_complete, no_failures = await licitacoes.collect(start, end, municipality)
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o PNCP") from error
    recent = sorted(items, key=lambda item: str(item.get("dataPublicacaoPncp") or ""), reverse=True)[:30]
    return {
        **licitacoes.summarize(items, total), "recentes": [licitacoes.shape_item(item) for item in recent],
        "data_inicial": start.isoformat(), "data_final": end.isoformat(),
        "consulta_completa": no_failures, "amostra_limitada": not sample_complete,
    }


@app.get("/api/admin/empresas")
def admin_companies(_: dict = Depends(auth.require_admin)):
    return [{**row, "rotulo": assess_eligibility(row).rotulo} for row in list_companies()]


@app.post("/api/admin/empresas", status_code=201)
async def admin_create_company(body: CompanyCreate, actor: dict = Depends(auth.require_admin)):
    cnpj = validate_cnpj(body.cnpj)
    if get_db() is None:
        raise HTTPException(503, "Banco de dados indisponível")
    if get_company(cnpj):
        raise HTTPException(409, "Empresa já cadastrada")
    fields = {"cnpj": cnpj, "raw_data": {}, "password_hash": auth.hash_password(body.senha), "ativo": True}
    try:
        remote = normalize_company(await get_open_cnpj(cnpj), cnpj)
        fields.update({key: remote[key] for key in ("razao_social", "nome_fantasia", "porte", "situacao_cadastral", "natureza_juridica", "natureza_juridica_codigo", "cnae_principal", "raw_data")})
    except httpx.HTTPError:
        pass
    if body.razao_social:
        fields["razao_social"] = body.razao_social
    if body.porte:
        fields["porte"] = body.porte
    saved = upsert_company_fields(fields)
    if saved is None:
        raise HTTPException(503, "Não foi possível salvar a empresa")
    log_event("empresa_criada", actor=actor["sub"], detail={"cnpj": cnpj})
    return public_company(saved)


@app.patch("/api/admin/empresas/{cnpj}")
def admin_update_company(cnpj: str, body: CompanyUpdate, actor: dict = Depends(auth.require_admin)):
    cnpj = validate_cnpj(cnpj)
    if not get_company(cnpj):
        raise HTTPException(404, "Empresa não encontrada")
    fields = {}
    if body.ativo is not None:
        fields["ativo"] = body.ativo
    if body.porte:
        fields["porte"] = body.porte
    if body.senha:
        fields["password_hash"] = auth.hash_password(body.senha)
    if not fields:
        raise HTTPException(400, "Nenhuma alteração informada")
    saved = update_company(cnpj, fields)
    if saved is None:
        raise HTTPException(503, "Não foi possível atualizar a empresa")
    log_event("empresa_atualizada", actor=actor["sub"], detail={"cnpj": cnpj, "campos": [key.replace("password_hash", "senha") for key in fields]})
    return public_company(saved)


@app.delete("/api/admin/empresas/{cnpj}", status_code=204)
def admin_delete_company(cnpj: str, actor: dict = Depends(auth.require_admin)):
    cnpj = validate_cnpj(cnpj)
    if not delete_company(cnpj):
        raise HTTPException(503, "Não foi possível remover a empresa")
    log_event("empresa_removida", actor=actor["sub"], detail={"cnpj": cnpj}, level="warning")


@app.get("/api/admin/logs")
def admin_logs(nivel: str | None = Query(None, pattern=r"^(info|warning|error)$"), limite: int = Query(200, ge=1, le=500), _: dict = Depends(auth.require_admin)):
    return list_logs(limite, nivel)
