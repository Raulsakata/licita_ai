import httpx
from src.config import settings


async def get_pncp_contracts(params: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{settings.pncp_base_url}/contratacoes/publicacao", params=params, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()


async def get_open_cnpj(cnpj: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{settings.open_cnpj_base_url}/{cnpj}", headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()


async def get_ibge_regions() -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{settings.ibge_base_url}/regioes", params={"orderBy": "nome"})
        response.raise_for_status()
        return response.json()


async def get_ibge_municipalities(region_id: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{settings.ibge_base_url}/regioes/{region_id}/municipios", params={"orderBy": "nome"})
        response.raise_for_status()
        return response.json()
