import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
import httpx
from src.config import settings

_response_cache: dict[tuple, tuple[float, object]] = {}
_cache_lock = asyncio.Lock()
_pncp_semaphore = asyncio.Semaphore(1)
_pncp_start_lock = asyncio.Lock()
_pncp_min_interval_seconds = 1.0
_pncp_last_request_at = 0.0
_pncp_cooldown_until = 0.0
PNCP_MAX_RETRIES = 6
PNCP_DEFAULT_429_COOLDOWN_SECONDS = 15.0


async def clear_response_cache() -> None:
    async with _cache_lock:
        _response_cache.clear()


async def invalidate_response_cache(url: str, params: dict | None = None) -> None:
    cache_key = (url, tuple(sorted((params or {}).items())))
    async with _cache_lock:
        _response_cache.pop(cache_key, None)


async def _get_json(
    url: str, params: dict | None = None, cache_ttl: int = 0,
    pncp: bool = False, max_retries: int | None = None,
) -> dict | list:
    global _pncp_last_request_at, _pncp_cooldown_until
    retry_limit = settings.external_api_max_retries if max_retries is None else max_retries
    cache_key = (url, tuple(sorted((params or {}).items())))
    now = time.monotonic()
    if cache_ttl > 0:
        async with _cache_lock:
            cached = _response_cache.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]

    for attempt in range(retry_limit + 1):
        try:
            if pncp:
                async with _pncp_semaphore:
                    async with _pncp_start_lock:
                        now = time.monotonic()
                        delay = max(
                            _pncp_min_interval_seconds - (now - _pncp_last_request_at),
                            _pncp_cooldown_until - now,
                        )
                        if delay > 0:
                            await asyncio.sleep(delay)
                        _pncp_last_request_at = time.monotonic()
                    async with httpx.AsyncClient(timeout=15) as client:
                        response = await client.get(url, params=params, headers={"Accept": "application/json"})
            else:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(url, params=params, headers={"Accept": "application/json"})
        except httpx.TransportError:
            if attempt >= retry_limit:
                raise
            await asyncio.sleep(min(1.0 * (2 ** attempt), 8.0))
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < retry_limit:
                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = max(float(retry_after), 0.25)
                except ValueError:
                    try:
                        retry_at = parsedate_to_datetime(retry_after)
                        if retry_at.tzinfo is None:
                            retry_at = retry_at.replace(tzinfo=timezone.utc)
                        delay = max((retry_at - datetime.now(timezone.utc)).total_seconds(), 0.25)
                    except (TypeError, ValueError, OverflowError):
                        delay = PNCP_DEFAULT_429_COOLDOWN_SECONDS if response.status_code == 429 else min(1.0 * (2 ** attempt), 30.0)
                if pncp and response.status_code == 429:
                    async with _pncp_start_lock:
                        _pncp_cooldown_until = max(_pncp_cooldown_until, time.monotonic() + min(delay, 120.0))
                else:
                    await asyncio.sleep(min(delay, 120.0))
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


async def _get_pncp_json(url: str, params: dict) -> dict:
    return await _get_json(
        url, params, settings.pncp_cache_ttl_seconds,
        pncp=True, max_retries=PNCP_MAX_RETRIES,
    )


async def get_pncp_contracts(params: dict) -> dict:
    return await _get_pncp_json(f"{settings.pncp_base_url}/contratacoes/publicacao", params)


async def invalidate_pncp_contract_page(params: dict) -> None:
    await invalidate_response_cache(f"{settings.pncp_base_url}/contratacoes/publicacao", params)


async def get_pncp_proposals(params: dict) -> dict:
    return await _get_pncp_json(f"{settings.pncp_base_url}/contratacoes/proposta", params)


async def invalidate_pncp_proposal_page(params: dict) -> None:
    await invalidate_response_cache(f"{settings.pncp_base_url}/contratacoes/proposta", params)


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


async def get_ibge_state_mesh(state_id: int) -> dict:
    return await _get_json(
        f"https://servicodados.ibge.gov.br/api/v3/malhas/estados/{state_id}",
        {"intrarregiao": "municipio", "formato": "application/vnd.geo+json", "qualidade": "minima"},
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
