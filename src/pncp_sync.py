import asyncio
from datetime import date, datetime, timedelta, timezone
from src import licitacoes
from src.db import (
    get_db, get_pncp_open_sync_state, get_pncp_sync_state,
    list_pncp_sync_windows, load_pncp_open_snapshot, load_pncp_results,
    save_pncp_open_snapshot, save_pncp_results, save_pncp_sync_window,
    update_pncp_open_sync_state, update_pncp_sync_state,
)
from src.logger import logger

SYNC_INTERVAL = timedelta(hours=12)
INITIAL_BACKFILL_DAYS = 7
REFRESH_LOOKBACK_DAYS = 30
_sync_lock = asyncio.Lock()
_open_sync_lock = asyncio.Lock()


def _date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _missing_ranges(start: date, end: date, windows: list[dict]) -> list[tuple[date, date]]:
    covered = sorted(
        ((_date(row["starts_on"]), _date(row["ends_on"])) for row in windows),
        key=lambda interval: interval[0],
    )
    gaps = []
    cursor = start
    for window_start, window_end in covered:
        if window_end < cursor:
            continue
        if window_start > end:
            break
        if window_start > cursor:
            gaps.append((cursor, min(end, window_start - timedelta(days=1))))
        cursor = max(cursor, window_end + timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


def _items_from_rows(rows: list[dict], municipality: str | None, modalities: tuple[int, ...]) -> list[dict]:
    items = {}
    for row in rows:
        item = row.get("raw_data") or {}
        if not licitacoes.is_ceara(item):
            continue
        if municipality and str(row.get("municipality_ibge_code") or "") != municipality:
            continue
        try:
            modality = int(item.get("modalidadeId") or 0)
        except (TypeError, ValueError):
            modality = 0
        if modality not in modalities:
            continue
        identifier = row.get("pncp_id") or item.get("numeroControlePNCP")
        if identifier:
            items[str(identifier)] = item
    return list(items.values())


async def _read_cached_period(start: date, end: date, municipality: str | None, modalities: tuple[int, ...]) -> list[dict]:
    rows = await asyncio.to_thread(load_pncp_results, start, end, municipality)
    if rows is None:
        raise RuntimeError("Não foi possível carregar licitações do Supabase")
    return _items_from_rows(rows, municipality, modalities)


def _period_is_covered(start: date, end: date, modalities: tuple[int, ...], windows: list[dict]) -> bool:
    return all(
        not _missing_ranges(start, end, [row for row in windows if int(row["modality_code"]) == modality])
        for modality in modalities
    )


async def collect(
    start: date,
    end: date,
    municipality: str | None = None,
    modalities: tuple[int, ...] = licitacoes.DEFAULT_MODALITIES,
    force_refresh: bool = False,
) -> tuple[int, list[dict], bool, bool]:
    if get_db() is None:
        return await licitacoes.collect(start, end, municipality, modalities)

    windows = await asyncio.to_thread(list_pncp_sync_windows, list(modalities))
    if windows is None:
        raise RuntimeError("Não foi possível consultar a cobertura PNCP no Supabase")
    if not force_refresh and _period_is_covered(start, end, modalities, windows):
        cached_items = await _read_cached_period(start, end, municipality, modalities)
        return len(cached_items), cached_items, True, True

    async with _sync_lock:
        windows = await asyncio.to_thread(list_pncp_sync_windows, list(modalities))
        if windows is None:
            raise RuntimeError("Não foi possível consultar a cobertura PNCP no Supabase")

        sample_complete = True
        no_failures = True
        page_semaphore = asyncio.Semaphore(licitacoes.PAGE_CONCURRENCY)
        for modality in modalities:
            modality_windows = [row for row in windows if int(row["modality_code"]) == modality]
            gaps = [(start, end)] if force_refresh else _missing_ranges(start, end, modality_windows)
            for gap_start, gap_end in gaps:
                try:
                    total, items, complete, succeeded = await licitacoes._fetch_modality(
                        modality, gap_start, gap_end, None, page_semaphore,
                    )
                except Exception as error:
                    logger.warning("Falha na sincronização PNCP modalidade=%s período=%s..%s: %s", modality, gap_start, gap_end, error)
                    sample_complete = False
                    no_failures = False
                    continue

                ceara_items = [item for item in items if licitacoes.is_ceara(item)]
                saved = await asyncio.to_thread(save_pncp_results, {"data": ceara_items})
                if not complete or not succeeded or not saved:
                    sample_complete = False
                    no_failures = no_failures and succeeded
                    continue

                window_saved = await asyncio.to_thread(
                    save_pncp_sync_window, modality, gap_start, gap_end, total, len(ceara_items),
                )
                if not window_saved:
                    sample_complete = False
                    no_failures = False
                else:
                    windows.append({
                        "modality_code": modality, "starts_on": gap_start.isoformat(),
                        "ends_on": gap_end.isoformat(),
                    })

        items = await _read_cached_period(start, end, municipality, modalities)
        coverage_ok = _period_is_covered(start, end, modalities, windows)
        sample_complete = sample_complete and coverage_ok
        return len(items), items, sample_complete, no_failures


async def fetch_open_cached(municipality: str | None, today: date, force_refresh: bool = False) -> tuple[int, list[dict], bool, bool]:
    if get_db() is None:
        return await licitacoes.fetch_open(municipality, today)

    async with _open_sync_lock:
        state = await asyncio.to_thread(get_pncp_open_sync_state)
        now = datetime.now(timezone.utc)
        last_started = _parse_timestamp((state or {}).get("last_started_at"))
        if not force_refresh and last_started and now - last_started < SYNC_INTERVAL:
            rows = await asyncio.to_thread(load_pncp_open_snapshot, municipality)
            if rows is None:
                raise RuntimeError("Não foi possível carregar o snapshot de editais abertos no Supabase")
            items = [row.get("raw_data") or {} for row in rows]
            is_complete = (state or {}).get("status") == "complete"
            return len(items), items, is_complete, is_complete

        started_at = now.isoformat()
        await asyncio.to_thread(update_pncp_open_sync_state, "running", started_at=started_at)
        try:
            total, fetched, complete, no_failures = await licitacoes.fetch_open(None, today)
        except Exception as error:
            await asyncio.to_thread(update_pncp_open_sync_state, "error", error=str(error))
            rows = await asyncio.to_thread(load_pncp_open_snapshot, municipality)
            if rows is None:
                raise
            stale_items = [row.get("raw_data") or {} for row in rows]
            return len(stale_items), stale_items, False, False

        saved = await asyncio.to_thread(save_pncp_open_snapshot, fetched)
        is_complete = complete and no_failures and saved
        completed_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            update_pncp_open_sync_state,
            "complete" if is_complete else "incomplete",
            completed_at=completed_at if is_complete else None,
            total_records=total,
            error=None if is_complete else "Snapshot parcial; a próxima execução tentará novamente.",
        )
        rows = await asyncio.to_thread(load_pncp_open_snapshot, municipality)
        if rows is None:
            raise RuntimeError("Não foi possível carregar o snapshot de editais abertos no Supabase")
        items = [row.get("raw_data") or {} for row in rows]
        return len(items), items, is_complete, no_failures and saved


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def run_scheduled_sync() -> dict:
    if get_db() is None:
        logger.warning("Sincronização agendada ignorada: Supabase não configurado")
        return {"status": "unavailable"}

    async with _sync_lock:
        state = await asyncio.to_thread(get_pncp_sync_state)
        now = datetime.now(timezone.utc)
        last_started = _parse_timestamp((state or {}).get("last_started_at"))
        if last_started and now - last_started < SYNC_INTERVAL:
            return {"status": "not_due", "last_started_at": last_started.isoformat()}

        last_completed = _parse_timestamp((state or {}).get("last_completed_at"))
        start = date.today() - timedelta(days=REFRESH_LOOKBACK_DAYS if last_completed else INITIAL_BACKFILL_DAYS)
        end = date.today()
        await asyncio.to_thread(update_pncp_sync_state, "running", started_at=now.isoformat())

    try:
        total, items, complete, no_failures = await collect(start, end, force_refresh=True)
        _, open_items, open_complete, open_no_failures = await fetch_open_cached(None, end, force_refresh=True)
        complete = complete and open_complete
        no_failures = no_failures and open_no_failures
        finished_at = datetime.now(timezone.utc).isoformat()
        status = "complete" if complete and no_failures else "incomplete"
        error = None if status == "complete" else "PNCP não entregou todas as páginas; a próxima execução tentará novamente."
        await asyncio.to_thread(
            update_pncp_sync_state, status,
            completed_at=finished_at if status == "complete" else None, error=error,
        )
        logger.info("Sincronização PNCP %s: %s registros (%s..%s)", status, total, start, end)
        return {"status": status, "total": total, "loaded": len(items), "started_at": now.isoformat(), "completed_at": finished_at}
    except Exception as error:
        finished_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            update_pncp_sync_state, "error", error=str(error),
        )
        logger.exception("Falha na sincronização agendada do PNCP")
        return {"status": "error", "completed_at": finished_at}


async def scheduler_loop() -> None:
    while True:
        try:
            await run_scheduled_sync()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro inesperado no agendador PNCP")
        await asyncio.sleep(15 * 60)


async def sync_status() -> dict:
    state = await asyncio.to_thread(get_pncp_sync_state)
    open_state = await asyncio.to_thread(get_pncp_open_sync_state)
    if not state:
        return {
            "status": "not_configured", "last_started_at": None, "last_completed_at": None,
            "open_status": (open_state or {}).get("status"),
            "open_last_completed_at": (open_state or {}).get("last_completed_at"),
        }
    return {
        "status": state.get("status"),
        "last_started_at": state.get("last_started_at"),
        "last_completed_at": state.get("last_completed_at"),
        "updated_at": state.get("updated_at"),
        "open_status": (open_state or {}).get("status"),
        "open_last_completed_at": (open_state or {}).get("last_completed_at"),
    }
