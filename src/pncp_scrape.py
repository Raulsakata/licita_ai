import asyncio
import re
import time
import unicodedata

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from src.config import settings
from src.db import (
    claim_pncp_html_scrapes,
    mark_pncp_html_scrape_complete,
    mark_pncp_html_scrape_failed,
    save_pncp_html_capture,
)
from src.logger import logger


FIELD_LABELS = {
    "id contratacao pncp": "numero_controle_pncp",
    "objeto": "objeto",
    "informacao complementar": "informacao_complementar",
    "modalidade da contratacao": "modalidade",
    "situacao": "situacao",
    "data de divulgacao no pncp": "data_divulgacao_pncp",
    "data de inicio de recebimento de propostas": "data_inicio_propostas",
    "data fim de recebimento de propostas": "data_fim_propostas",
    "valor total estimado da compra": "valor_total_estimado",
}
_user_agent_index = 0


class HtmlCaptureError(ValueError):
    pass


def _normalize_label(value: str) -> str:
    ascii_label = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_label.casefold()).strip()


def _next_user_agent() -> str:
    """Alterna identificadores configurados sem mascarar a identidade do coletor."""
    global _user_agent_index
    configured_agents = [
        agent.strip()
        for agent in settings.pncp_scrape_user_agent_pool.split("|")
        if agent.strip()
    ]
    agents = list(dict.fromkeys(configured_agents)) or [settings.pncp_scrape_user_agent]
    if not agents[0]:
        raise RuntimeError("Configure ao menos um User-Agent identificável para a captura PNCP")
    user_agent = agents[_user_agent_index % len(agents)]
    _user_agent_index += 1
    return user_agent


def extract_visible_fields(page_text: str, expected_id: str) -> dict:
    """Extrai campos por rótulo da página renderizada e valida a identidade do edital."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in page_text.splitlines()]
    lines = [line for line in lines if line]
    fields = {}
    for index, line in enumerate(lines):
        if ":" not in line:
            continue
        label, inline_value = line.split(":", 1)
        field_name = FIELD_LABELS.get(_normalize_label(label))
        if not field_name:
            continue
        value = inline_value.strip()
        if not value:
            for candidate in lines[index + 1:]:
                next_label = candidate.split(":", 1)[0] if ":" in candidate else ""
                if _normalize_label(next_label) in FIELD_LABELS:
                    break
                value = candidate
                break
        if value:
            fields[field_name] = value

    if fields.get("numero_controle_pncp") != expected_id:
        raise HtmlCaptureError("Identificador PNCP ausente ou diferente do registro consultado")
    if not fields.get("objeto"):
        raise HtmlCaptureError("Campo obrigatório ausente na página do PNCP: objeto")
    return fields


async def _capture_page(page, job: dict) -> dict:
    response = await page.goto(
        job["page_url"],
        wait_until="domcontentloaded",
        timeout=settings.pncp_scrape_timeout_seconds * 1000,
    )
    if response is None or response.status >= 400:
        status = response.status if response is not None else "sem resposta HTTP"
        raise HtmlCaptureError(f"Página pública PNCP respondeu com {status}")
    await page.get_by_text("Id contratação PNCP", exact=False).wait_for(
        timeout=settings.pncp_scrape_timeout_seconds * 1000,
    )
    page_text = await page.locator("main").inner_text(
        timeout=settings.pncp_scrape_timeout_seconds * 1000,
    )
    return extract_visible_fields(page_text, str(job["pncp_id"]))


async def process_queue() -> dict:
    jobs = await asyncio.to_thread(claim_pncp_html_scrapes, settings.pncp_scrape_batch_size)
    if jobs is None:
        return {"status": "unavailable", "processed": 0, "failed": 0}
    if not jobs:
        return {"status": "idle", "processed": 0, "failed": 0}

    processed = 0
    failed = 0
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=_next_user_agent(),
                    locale="pt-BR",
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "pt-BR,pt;q=0.9",
                        "Cache-Control": "no-cache",
                    },
                )
                page = await context.new_page()
                last_request_at = 0.0
                for job in jobs:
                    delay = settings.pncp_scrape_min_interval_seconds - (time.monotonic() - last_request_at)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    last_request_at = time.monotonic()
                    try:
                        fields = await _capture_page(page, job)
                        saved = await asyncio.to_thread(
                            save_pncp_html_capture, job["pncp_id"], job["page_url"], fields,
                        )
                        if not saved:
                            raise RuntimeError("Captura HTML não pôde ser persistida no Supabase")
                        completed = await asyncio.to_thread(
                            mark_pncp_html_scrape_complete, job["pncp_id"],
                        )
                        if not completed:
                            raise RuntimeError("Não foi possível concluir o registro da fila de scraping")
                        processed += 1
                    except (HtmlCaptureError, PlaywrightError, RuntimeError) as error:
                        logger.warning(
                            "Captura HTML PNCP não concluída id=%s: %s",
                            job.get("pncp_id"), error,
                        )
                        await asyncio.to_thread(mark_pncp_html_scrape_failed, job, str(error))
                        failed += 1
                await context.close()
            finally:
                await browser.close()
    except PlaywrightError:
        logger.exception("Não foi possível iniciar o navegador headless do PNCP")
        for job in jobs:
            await asyncio.to_thread(
                mark_pncp_html_scrape_failed, job, "Falha ao iniciar o navegador headless",
            )
        failed += len(jobs)
    except ImportError:
        logger.exception("Playwright não está instalado; a fila de scraping PNCP foi mantida para retry")
        for job in jobs:
            await asyncio.to_thread(
                mark_pncp_html_scrape_failed, job, "Playwright não está instalado",
            )
        failed += len(jobs)

    status = "complete" if not failed else "incomplete"
    logger.info("Scraping HTML PNCP %s: capturados=%s falhas=%s", status, processed, failed)
    return {"status": status, "processed": processed, "failed": failed}
