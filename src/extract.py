import asyncio
import time
import httpx
from src.config import settings

_response_cache: dict[tuple, tuple[float, object]] = {}
_cache_lock = asyncio.Lock()


async def clear_response_cache() -> None:
    async with _cache_lock:
        _response_cache.clear()


async def _get_json(url: str, params: dict | None = None, cache_ttl: int = 0) -> dict | list:
    cache_key = (url, tuple(sorted((params or {}).items())))
    now = time.monotonic()
    if cache_ttl > 0:
        async with _cache_lock:
            cached = _response_cache.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]

    for attempt in range(settings.external_api_max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url, params=params, headers={"Accept": "application/json"})
        except httpx.TransportError:
            if attempt >= settings.external_api_max_retries:
                raise
            await asyncio.sleep(min(0.25 * (2 ** attempt), 2.0))
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < settings.external_api_max_retries:
                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = min(max(float(retry_after), 0.25), 2.0)
                except ValueError:
                    delay = min(0.25 * (2 ** attempt), 2.0)
                await asyncio.sleep(delay)
                continue
        response.raise_for_status()
        payload = {"data": [], "totalRegistros": 0, "totalPaginas": 0} if response.status_code == 204 else response.json()
        if cache_ttl > 0:
            async with _cache_lock:
                if len(_response_cache) >= 1000:
                    expired_keys = [key for key, value in _response_cache.items() if value[0] <= time.monotonic()]
                    for key in expired_keys:
                        _response_cache.pop(key, None)
                    if len(_response_cache) >= 1000:
                        oldest_key = min(_response_cache, key=lambda key: _response_cache[key][0])
                        _response_cache.pop(oldest_key, None)
                _response_cache[cache_key] = (time.monotonic() + cache_ttl, payload)
        return payload
    raise RuntimeError("A chamada externa excedeu o limite de tentativas")


async def get_pncp_contracts(params: dict) -> dict:
    return await _get_json(
        f"{settings.pncp_base_url}/contratacoes/publicacao", params,
        settings.pncp_cache_ttl_seconds,
    )


async def get_pncp_proposals(params: dict) -> dict:
    return await _get_json(
        f"{settings.pncp_base_url}/contratacoes/proposta", params,
        settings.pncp_cache_ttl_seconds,
    )


async def get_open_cnpj(cnpj: str) -> dict:
    return await _get_json(
        f"{settings.open_cnpj_base_url}/{cnpj}",
        cache_ttl=settings.open_cnpj_cache_ttl_seconds,
    )


async def get_ibge_state_municipalities(state_id: int) -> list[dict]:
    return await _get_json(
        f"{settings.ibge_base_url}/estados/{state_id}/municipios", {"orderBy": "nome"},
        settings.ibge_cache_ttl_seconds,
    )


async def get_ibge_regions() -> list[dict]:
    return await _get_json(
        f"{settings.ibge_base_url}/regioes", {"orderBy": "nome"},
        settings.ibge_cache_ttl_seconds,
    )


async def get_ibge_municipalities(region_id: int) -> list[dict]:
    return await _get_json(
        f"{settings.ibge_base_url}/regioes/{region_id}/municipios", {"orderBy": "nome"},
        settings.ibge_cache_ttl_seconds,
    )
