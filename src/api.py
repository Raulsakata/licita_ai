from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
from src.config import settings
from src.db import create_saved_search, delete_saved_search, get_db, list_saved_searches, save_company, save_pncp_results
from src.domain import PNCP_MODALIDADES
from src.extract import get_ibge_municipalities, get_ibge_regions, get_pncp_contracts
from src.load import load_company_assessment
from src.schemas import SavedSearchCreate
from src.validators import validate_cnpj

MODALIDADE_CODES = {item["codigo"] for item in PNCP_MODALIDADES}

app = FastAPI(title="Licita AI API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.frontend_origin.split(",")], allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok", "integrations": {"pncp": "configured", "open_cnpj": "configured", "supabase": "configured" if get_db() else "pending"}}


@app.get("/api/pncp/modalidades")
def pncp_modalidades():
    return PNCP_MODALIDADES


@app.get("/api/consultas-salvas")
def saved_searches_list():
    return list_saved_searches()


@app.post("/api/consultas-salvas", status_code=201)
def saved_searches_create(body: SavedSearchCreate):
    created = create_saved_search(body.name, body.filters)
    if created is None:
        raise HTTPException(503, "Supabase não configurado")
    return created


@app.delete("/api/consultas-salvas/{search_id}", status_code=204)
def saved_searches_delete(search_id: str):
    delete_saved_search(search_id)


@app.get("/api/empresas/{cnpj}/elegibilidade")
async def company_eligibility(cnpj: str):
    clean_cnpj = validate_cnpj(cnpj)
    try:
        company, eligibility = await load_company_assessment(clean_cnpj)
        save_company(company, eligibility.model_dump())
        return eligibility
    except httpx.HTTPStatusError as error:
        raise HTTPException(error.response.status_code, "Empresa não encontrada no OpenCNPJ") from error
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o OpenCNPJ") from error


@app.get("/api/geografia/regioes")
async def regions():
    try:
        return await get_ibge_regions()
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o IBGE") from error


@app.get("/api/geografia/regioes/{region_id}/municipios")
async def municipalities(region_id: int):
    try:
        return await get_ibge_municipalities(region_id)
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o IBGE") from error


@app.get("/api/pncp/contratacoes")
async def pncp_contracts(
    codigoModalidadeContratacao: int = Query(..., ge=1, le=13),
    dataInicial: str = Query(default_factory=lambda: (datetime.now() - timedelta(days=7)).strftime("%Y%m%d"), pattern=r"^\d{8}$"),
    dataFinal: str = Query(default_factory=lambda: datetime.now().strftime("%Y%m%d"), pattern=r"^\d{8}$"),
    pagina: int = Query(1, ge=1), tamanhoPagina: int = Query(10, ge=10, le=50),
):
    if dataInicial > dataFinal:
        raise HTTPException(400, "A data inicial deve ser anterior à final")
    if codigoModalidadeContratacao not in MODALIDADE_CODES:
        raise HTTPException(400, "Código de modalidade de contratação inválido")
    params = {
        "dataInicial": dataInicial, "dataFinal": dataFinal, "pagina": pagina, "tamanhoPagina": tamanhoPagina,
        "codigoModalidadeContratacao": codigoModalidadeContratacao,
    }
    try:
        payload = await get_pncp_contracts(params)
        save_pncp_results(payload)
        return payload
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o PNCP") from error


@app.get("/api/municipios/{municipality_code}/licitacoes")
async def city_contracts(
    municipality_code: str,
    codigoModalidadeContratacao: int = Query(..., ge=1, le=13),
    dataInicial: str = Query(default_factory=lambda: (datetime.now() - timedelta(days=30)).strftime("%Y%m%d"), pattern=r"^\d{8}$"),
    dataFinal: str = Query(default_factory=lambda: datetime.now().strftime("%Y%m%d"), pattern=r"^\d{8}$"),
    pagina: int = Query(1, ge=1), tamanhoPagina: int = Query(20, ge=10, le=50),
):
    if not municipality_code.isdigit() or len(municipality_code) != 7:
        raise HTTPException(400, "Código IBGE do município inválido")
    if dataInicial > dataFinal:
        raise HTTPException(400, "A data inicial deve ser anterior à final")
    if codigoModalidadeContratacao not in MODALIDADE_CODES:
        raise HTTPException(400, "Código de modalidade de contratação inválido")
    params = {
        "dataInicial": dataInicial, "dataFinal": dataFinal, "codigoMunicipioIbge": municipality_code,
        "pagina": pagina, "tamanhoPagina": tamanhoPagina, "codigoModalidadeContratacao": codigoModalidadeContratacao,
    }
    try:
        payload = await get_pncp_contracts(params)
        save_pncp_results(payload, municipality_code)
        return payload
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o PNCP") from error
