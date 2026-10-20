"""Executa as rotinas periódicas fora do processo que atende requisições HTTP."""

import asyncio
from datetime import datetime, timedelta, timezone

from src import extract, licitacoes, pncp_scrape, pncp_sync, tce_expenses
from src.config import settings
from src.db import get_db, get_geographic_reference, save_geographic_reference
from src.logger import logger


async def scrape_queue_loop() -> None:
    """Consome lotes de captura em segundo plano, respeitando a pausa configurada."""
    while True:
        try:
            result = await pncp_scrape.process_queue()
            if result["status"] == "unavailable":
                logger.warning("Fila HTML PNCP indisponível; nova tentativa em %s s", settings.pncp_scrape_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro no worker da fila HTML PNCP; a execução será retomada")
        await asyncio.sleep(settings.pncp_scrape_poll_seconds)


async def refresh_geographic_references() -> None:
    """Sincroniza nomes e malha do Ceará no banco com a cadência oficial de cache."""
    references = (
        ("ceara_municipalities", lambda: extract.get_ibge_state_municipalities(int(licitacoes.IBGE_UF_CODE))),
        ("ceara_map", lambda: extract.get_ibge_state_mesh(int(licitacoes.IBGE_UF_CODE))),
    )
    now = datetime.now(timezone.utc)
    for reference_key, fetch in references:
        current = await asyncio.to_thread(get_geographic_reference, reference_key)
        fetched_at = (current or {}).get("fetched_at")
        try:
            fetched = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            fetched = None
        if fetched and now - fetched < timedelta(seconds=settings.ibge_cache_ttl_seconds):
            continue

        payload = await fetch()
        saved = await asyncio.to_thread(save_geographic_reference, reference_key, payload)
        if not saved:
            raise RuntimeError(f"Não foi possível persistir a referência geográfica {reference_key}")
        logger.info("Referência geográfica atualizada no Supabase: %s", reference_key)


async def geography_refresh_loop() -> None:
    """Atualiza dados territoriais diariamente e tenta de novo após falhas temporárias."""
    while True:
        try:
            await refresh_geographic_references()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao atualizar referências geográficas; nova tentativa em 15 minutos")
            await asyncio.sleep(15 * 60)
            continue
        await asyncio.sleep(settings.ibge_cache_ttl_seconds)


async def run_worker() -> None:
    """Inicia sincronização e captura somente quando o banco está configurado."""
    if get_db() is None:
        raise RuntimeError("Worker não iniciado: configure SUPABASE_URL e uma chave de servidor")
    logger.info("Worker PNCP iniciado; sincronização e scraping executam fora da API HTTP")
    await asyncio.gather(
        pncp_sync.scheduler_loop(),
        scrape_queue_loop(),
        geography_refresh_loop(),
        tce_sync_loop(),
    )


async def tce_sync_loop() -> None:
    """Processa em background a fila de sincronização de compras municipais (TCE-CE)."""
    while True:
        try:
            result = await tce_expenses.process_sync_queue(batch_size=1)
            if result.get("status") == "ok" and result.get("processed"):
                logger.info("Sincronização TCE concluída para %s item(ns) da fila", result["processed"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha no worker de sincronização TCE; nova tentativa em %s s", settings.tce_sync_poll_seconds)
        await asyncio.sleep(settings.tce_sync_poll_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker())
