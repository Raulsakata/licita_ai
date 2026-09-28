from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
from src.config import settings
from src.db import get_db, save_company, save_pncp_results
from src.extract import get_ibge_municipalities, get_ibge_regions, get_pncp_contracts
from src.load import load_company_assessment
from src.validators import validate_cnpj

app = FastAPI(title="Licita AI API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.frontend_origin.split(",")], allow_methods=["GET"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok", "integrations": {"pncp": "configured", "open_cnpj": "configured", "supabase": "configured" if get_db() else "pending"}}


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
    dataInicial: str = Query(default_factory=lambda: (datetime.now() - timedelta(days=7)).strftime("%Y%m%d"), pattern=r"^\d{8}$"),
    dataFinal: str = Query(default_factory=lambda: datetime.now().strftime("%Y%m%d"), pattern=r"^\d{8}$"),
    pagina: int = Query(1, ge=1), tamanhoPagina: int = Query(10, ge=1, le=50), codigoModalidadeContratacao: int | None = Query(None, gt=0),
):
    if dataInicial > dataFinal:
        raise HTTPException(400, "A data inicial deve ser anterior à final")
    params = {"dataInicial": dataInicial, "dataFinal": dataFinal, "pagina": pagina, "tamanhoPagina": tamanhoPagina}
    if codigoModalidadeContratacao:
        params["codigoModalidadeContratacao"] = codigoModalidadeContratacao
    try:
        payload = await get_pncp_contracts(params)
        save_pncp_results(payload)
        return payload
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o PNCP") from error


@app.get("/api/municipios/{municipality_code}/licitacoes")
async def city_contracts(
    municipality_code: str,
    dataInicial: str = Query(default_factory=lambda: (datetime.now() - timedelta(days=30)).strftime("%Y%m%d"), pattern=r"^\d{8}$"),
    dataFinal: str = Query(default_factory=lambda: datetime.now().strftime("%Y%m%d"), pattern=r"^\d{8}$"),
    pagina: int = Query(1, ge=1), tamanhoPagina: int = Query(20, ge=1, le=50), codigoModalidadeContratacao: int | None = Query(None, gt=0),
):
    if not municipality_code.isdigit() or len(municipality_code) != 7:
        raise HTTPException(400, "Código IBGE do município inválido")
    if dataInicial > dataFinal:
        raise HTTPException(400, "A data inicial deve ser anterior à final")
    params = {"dataInicial": dataInicial, "dataFinal": dataFinal, "codigoMunicipioIbge": municipality_code, "pagina": pagina, "tamanhoPagina": tamanhoPagina}
    if codigoModalidadeContratacao:
        params["codigoModalidadeContratacao"] = codigoModalidadeContratacao
    try:
        payload = await get_pncp_contracts(params)
        save_pncp_results(payload, municipality_code)
        return payload
    except httpx.HTTPError as error:
        raise HTTPException(502, "Falha ao consultar o PNCP") from error
