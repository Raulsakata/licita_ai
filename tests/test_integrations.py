import asyncio
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import HTTPException

import src.api as api
import src.auth as auth
import src.cnae as cnae
import src.licitacoes as licitacoes
import src.pncp_sync as pncp_sync
import src.db as db
import src.extract as extract
from src.schemas import Eligibility
from src.transform import assess_eligibility, normalize_opportunity


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get(self, url, *_args, **_kwargs):
        self.calls += 1
        self.urls.append(url)
        return self.responses.pop(0)


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await extract.clear_response_cache()

    async def test_pncp_retries_rate_limit_and_caches_success(self):
        client = FakeClient([
            FakeResponse(429, {}, {"Retry-After": "0"}),
            FakeResponse(200, {"data": [], "totalRegistros": 0}),
        ])
        with patch("src.extract.httpx.AsyncClient", return_value=client), patch("src.extract.asyncio.sleep", new_callable=AsyncMock):
            first = await extract.get_pncp_contracts({"uf": "BA", "pagina": 1})
            second = await extract.get_pncp_contracts({"uf": "BA", "pagina": 1})
        self.assertEqual(first, second)
        self.assertEqual(client.calls, 2)

    async def test_pncp_honors_retry_after_above_two_seconds(self):
        client = FakeClient([
            FakeResponse(429, {}, {"Retry-After": "4"}),
            FakeResponse(200, {"data": [], "totalRegistros": 0}),
        ])
        with patch("src.extract.httpx.AsyncClient", return_value=client), patch("src.extract.asyncio.sleep", new_callable=AsyncMock) as sleep, patch.object(
            extract, "_pncp_min_interval_seconds", 0,
        ), patch.object(extract, "_pncp_last_request_at", 0):
            await extract.get_pncp_contracts({"uf": "CE", "pagina": 987654})

        sleep.assert_awaited_once()
        self.assertAlmostEqual(sleep.await_args.args[0], 4.0, places=2)
        self.assertEqual(client.calls, 2)

    async def test_pncp_rate_limit_cooldown_applies_to_other_pages(self):
        client = FakeClient([
            FakeResponse(429, {}, {"Retry-After": "5"}),
            FakeResponse(200, {"data": [{"id": 1}]}),
            FakeResponse(200, {"data": [{"id": 2}]}),
        ])
        with patch("src.extract.httpx.AsyncClient", return_value=client), patch("src.extract.asyncio.sleep", new_callable=AsyncMock) as sleep, patch.object(
            extract, "_pncp_min_interval_seconds", 0,
        ), patch.object(extract, "_pncp_last_request_at", 0), patch.object(extract, "_pncp_cooldown_until", 0):
            first = await extract.get_pncp_contracts({"uf": "CE", "pagina": 1})
            second = await extract.get_pncp_contracts({"uf": "CE", "pagina": 2})

        self.assertEqual(first["data"][0]["id"], 1)
        self.assertEqual(second["data"][0]["id"], 2)
        self.assertEqual(client.calls, 3)
        self.assertEqual(sleep.await_count, 2)
        self.assertTrue(all(abs(call.args[0] - 5.0) < 0.02 for call in sleep.await_args_list))

    async def test_open_cnpj_and_ibge_use_shared_http_adapter(self):
        client = FakeClient([
            FakeResponse(200, {"cnpj": "11222333000181"}),
            FakeResponse(200, [{"id": 2, "nome": "Nordeste"}]),
            FakeResponse(200, [{"id": 2900000, "nome": "Município"}]),
        ])
        with patch("src.extract.httpx.AsyncClient", return_value=client):
            company = await extract.get_open_cnpj("11222333000181")
            regions = await extract.get_ibge_regions()
            cities = await extract.get_ibge_municipalities(2)
        self.assertEqual(company["cnpj"], "11222333000181")
        self.assertEqual(regions[0]["id"], 2)
        self.assertEqual(cities[0]["id"], 2900000)
        self.assertIn("api.opencnpj.org/11222333000181", client.urls[0])
        self.assertIn("/regioes", client.urls[1])
        self.assertIn("/regioes/2/municipios", client.urls[2])

    def test_supabase_prefers_server_secret_key(self):
        db.get_db.cache_clear()
        try:
            with patch.object(db.settings, "supabase_url", "https://project.supabase.co"), patch.object(db.settings, "supabase_secret_key", "server-secret"), patch.object(db.settings, "supabase_service_role_key", "legacy-secret"), patch.object(db, "create_client") as create_client:
                db.get_db()
            create_client.assert_called_once_with("https://project.supabase.co", "server-secret")
        finally:
            db.get_db.cache_clear()

    async def test_public_summary_queries_only_ceara(self):
        item = {
            "numeroControlePNCP": "1-1-1", "objetoCompra": "Cota reservada para microempresa", "valorTotalEstimado": 1250,
            "dataPublicacaoPncp": "2026-09-10T10:00:00", "modalidadeNome": "Pregão - Eletrônico",
            "unidadeOrgao": {"ufSigla": "CE", "municipioNome": "Fortaleza", "codigoIbge": "2304400"},
        }
        foreign = {**item, "numeroControlePNCP": "2-2-2", "unidadeOrgao": {"ufSigla": "BA", "municipioNome": "Salvador"}}
        pncp = AsyncMock(return_value={"totalRegistros": 2, "totalPaginas": 1, "data": [item, foreign]})
        with patch.object(pncp_sync, "get_db", MagicMock(return_value=None)), patch.object(licitacoes, "get_pncp_contracts", pncp):
            summary = await api.public_summary(None, "2026-09-01", "2026-09-30")
        params = [call.args[0] for call in pncp.await_args_list]
        self.assertTrue(all(p["uf"] == "CE" for p in params))
        self.assertEqual(summary["quantidade_amostra"], 1)
        self.assertEqual(summary["valor_total"], 1250)
        self.assertEqual(summary["por_municipio"][0]["municipio"], "Fortaleza")

    def test_sync_missing_ranges_only_returns_uncovered_dates(self):
        windows = [
            {"starts_on": "2026-09-01", "ends_on": "2026-09-05"},
            {"starts_on": "2026-09-09", "ends_on": "2026-09-12"},
        ]
        self.assertEqual(
            pncp_sync._missing_ranges(date(2026, 9, 1), date(2026, 9, 15), windows),
            [(date(2026, 9, 6), date(2026, 9, 8)), (date(2026, 9, 13), date(2026, 9, 15))],
        )

    def test_naive_pncp_deadline_is_treated_as_ceara_local_time(self):
        value = db.normalize_pncp_timestamp("2026-10-06T18:00:00")
        self.assertEqual(value, "2026-10-06T21:00:00+00:00")

    async def test_covered_sync_period_reads_supabase_without_calling_pncp(self):
        item = {
            "numeroControlePNCP": "cached-1", "modalidadeId": 6,
            "unidadeOrgao": {"ufSigla": "CE", "codigoIbge": "2304400"},
        }
        windows = [{"modality_code": 6, "starts_on": "2026-09-01", "ends_on": "2026-09-30"}]
        with patch.object(pncp_sync, "get_db", MagicMock(return_value=object())), patch.object(
            pncp_sync, "list_pncp_sync_windows", MagicMock(return_value=windows),
        ), patch.object(pncp_sync, "load_pncp_results", MagicMock(return_value=[{"pncp_id": "cached-1", "raw_data": item}])), patch.object(
            pncp_sync.licitacoes, "get_pncp_contracts", AsyncMock(),
        ) as pncp:
            total, items, complete, no_failures = await pncp_sync.collect(
                date(2026, 9, 1), date(2026, 9, 30), modalities=(6,),
            )

        self.assertEqual((total, len(items)), (1, 1))
        self.assertTrue(complete)
        self.assertTrue(no_failures)
        pncp.assert_not_awaited()

    async def test_sync_fetches_and_persists_only_uncovered_range(self):
        item = {
            "numeroControlePNCP": "fresh-1", "modalidadeId": 6,
            "unidadeOrgao": {"ufSigla": "CE", "codigoIbge": "2304400"},
        }
        with patch.object(pncp_sync, "get_db", MagicMock(return_value=object())), patch.object(
            pncp_sync, "list_pncp_sync_windows", MagicMock(return_value=[]),
        ), patch.object(pncp_sync, "load_pncp_results", MagicMock(return_value=[{"pncp_id": "fresh-1", "raw_data": item}])), patch.object(
            pncp_sync, "save_pncp_results", MagicMock(return_value=True),
        ) as save_rows, patch.object(
            pncp_sync, "save_pncp_sync_window", MagicMock(return_value=True),
        ) as save_window, patch.object(
            pncp_sync.licitacoes, "_fetch_modality", AsyncMock(return_value=(1, [item], True, True)),
        ) as fetch_modality:
            total, items, complete, no_failures = await pncp_sync.collect(
                date(2026, 9, 1), date(2026, 9, 30), modalities=(6,),
            )

        fetch_modality.assert_awaited_once()
        save_rows.assert_called_once_with({"data": [item]})
        save_window.assert_called_once_with(6, date(2026, 9, 1), date(2026, 9, 30), 1, 1)
        self.assertEqual((total, len(items)), (1, 1))
        self.assertTrue(complete)
        self.assertTrue(no_failures)

    async def test_scheduler_waits_twelve_hours_between_runs(self):
        started = (datetime.now(timezone.utc) - timedelta(hours=11)).isoformat()
        state = {"last_started_at": started, "last_completed_at": started}
        with patch.object(pncp_sync, "get_db", MagicMock(return_value=object())), patch.object(
            pncp_sync, "get_pncp_sync_state", MagicMock(return_value=state),
        ), patch.object(pncp_sync, "collect", AsyncMock()) as collect, patch.object(
            pncp_sync, "fetch_open_cached", AsyncMock(),
        ) as open_fetch:
            result = await pncp_sync.run_scheduled_sync()

        self.assertEqual(result["status"], "not_due")
        collect.assert_not_awaited()
        open_fetch.assert_not_awaited()

    async def test_scheduler_refreshes_recent_period_when_due(self):
        started = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        state = {"last_started_at": started, "last_completed_at": started}
        with patch.object(pncp_sync, "get_db", MagicMock(return_value=object())), patch.object(
            pncp_sync, "get_pncp_sync_state", MagicMock(return_value=state),
        ), patch.object(pncp_sync, "update_pncp_sync_state", MagicMock()), patch.object(
            pncp_sync, "collect", AsyncMock(return_value=(1, [{"id": "cached"}], True, True)),
        ) as collect, patch.object(
            pncp_sync, "fetch_open_cached", AsyncMock(return_value=(1, [], True, True)),
        ) as open_fetch:
            result = await pncp_sync.run_scheduled_sync()

        self.assertEqual(result["status"], "complete")
        self.assertEqual(collect.await_args.kwargs, {"force_refresh": True})
        open_fetch.assert_awaited_once_with(None, date.today(), force_refresh=True)
        self.assertEqual((collect.await_args.args[0], collect.await_args.args[1]), (
            date.today() - timedelta(days=pncp_sync.REFRESH_LOOKBACK_DAYS), date.today(),
        ))

    async def test_internal_sync_webhook_requires_shared_secret(self):
        with patch.object(api.settings, "pncp_sync_secret", "long-random-secret"), patch.object(
            pncp_sync, "run_scheduled_sync", AsyncMock(return_value={"status": "complete"}),
        ) as run_sync:
            with self.assertRaises(HTTPException) as raised:
                await api.internal_pncp_sync("wrong-secret")
            self.assertEqual(raised.exception.status_code, 401)
            result = await api.internal_pncp_sync("long-random-secret")

        self.assertEqual(result["status"], "complete")
        run_sync.assert_awaited_once()

    def test_rejects_other_states_and_bad_periods(self):
        with self.assertRaises(HTTPException):
            api.resolve_municipality("2900000")
        with self.assertRaises(HTTPException):
            api.resolve_period("2026-10-01", "2026-09-01")
        self.assertEqual(api.resolve_municipality("2304400"), "2304400")

    def test_eligibility_labels_non_me_epp_as_not_apt(self):
        base = {"cnpj": "11222333000181", "situacao_cadastral": "Ativa"}
        self.assertEqual(assess_eligibility({**base, "porte": "ME"}).rotulo, "Apta")
        self.assertEqual(assess_eligibility({**base, "porte": "Demais"}).rotulo, "Não Apta")
        self.assertEqual(assess_eligibility({**base, "porte": "ME", "natureza_juridica_codigo": "1015"}).rotulo, "Não Apta")

    def test_cached_opportunity_infers_ceara_uf_from_ibge_code(self):
        row = normalize_opportunity({
            "numeroControlePNCP": "ibge-only-1",
            "codigoMunicipioIbge": "2304400",
            "dataPublicacaoPncp": "2026-10-06T12:00:00",
        }, None)
        self.assertEqual(row["uf"], "CE")

    def test_tokens_and_passwords(self):
        stored = auth.hash_password("senha-forte-123")
        self.assertTrue(auth.verify_password("senha-forte-123", stored))
        self.assertFalse(auth.verify_password("outra", stored))
        token = auth.create_token("11222333000181", "empresa")
        self.assertEqual(auth.decode_token(token)["role"], "empresa")
        self.assertIsNone(auth.decode_token(token + "x"))
        with self.assertRaises(HTTPException):
            auth.require_admin(f"Bearer {token}")

    async def test_company_sees_only_apt_opportunities(self):
        row = {"cnpj": "11222333000181", "porte": "Demais", "situacao_cadastral": "Ativa", "ativo": True,
               "raw_data": {"cnaes": [{"codigo": "4784900", "descricao": "Comércio varejista de gás liquefeito de petróleo (GLP)"}]}}
        open_item = {"numeroControlePNCP": "1-1-1", "objetoCompra": "Aquisição de gás de cozinha GLP", "unidadeOrgao": {"ufSigla": "CE"}}
        unrelated = {"numeroControlePNCP": "3-3-3", "objetoCompra": "Aquisição de material de escritório", "unidadeOrgao": {"ufSigla": "CE"}}
        restricted = {"numeroControlePNCP": "2-2-2", "objetoCompra": "Gás - exclusiva para ME e EPP", "unidadeOrgao": {"ufSigla": "CE"}}
        pncp = AsyncMock(return_value={"totalRegistros": 3, "totalPaginas": 1, "data": [open_item, restricted, unrelated]})
        with patch.object(api, "get_company", MagicMock(return_value=row)), patch.object(pncp_sync, "get_db", MagicMock(return_value=None)), patch.object(licitacoes, "get_pncp_contracts", pncp):
            result = await api.company_opportunities(None, "2026-09-01", "2026-09-30", 6, {"sub": row["cnpj"], "role": "empresa"})
        self.assertEqual([i["id"] for i in result["aptas"]], ["1-1-1"])
        self.assertEqual(result["total_incompativeis"], 1)
        self.assertEqual(result["nao_aptas"][0]["status"], "Não Apta")

    def test_cnae_matcher_requires_related_terms(self):
        match, _ = cnae.build_matcher([{"codigo": "4784900", "descricao": "Comércio varejista de gás liquefeito de petróleo (GLP)"}])
        self.assertTrue(match("Aquisição de gás GLP para escolas"))
        self.assertFalse(match("Contratação de serviços de limpeza"))
        weak_only, _ = cnae.build_matcher([{"codigo": "1", "descricao": "Manutenção e reparação de veículos"}])
        self.assertFalse(weak_only("Manutenção predial"))
        self.assertTrue(weak_only("Manutenção de veículos da frota"))

    def test_closed_mpe_participation_by_month(self):
        items = [
            {"dataEncerramentoProposta": "2020-03-10T10:00:00", "objetoCompra": "Exclusivo para ME e EPP", "valorTotalEstimado": 100},
            {"dataEncerramentoProposta": "2020-03-20T10:00:00", "objetoCompra": "Aquisição geral", "valorTotalEstimado": 50},
            {"dataEncerramentoProposta": "2999-01-01T10:00:00", "objetoCompra": "Exclusivo para ME e EPP"},
        ]
        rows = licitacoes.closed_mpe_by_month(items)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["mes"], rows[0]["encerradas"], rows[0]["encerradas_mpe"], rows[0]["participacao_mpe"]), ("2020-03", 2, 1, 0.5))

    async def test_open_notices_report_missing_pages(self):
        first_page = {
            "totalRegistros": 120, "totalPaginas": 3,
            "data": [{"numeroControlePNCP": f"first-{i}", "unidadeOrgao": {"ufSigla": "CE"}} for i in range(50)],
        }
        third_page = {
            "data": [{"numeroControlePNCP": f"third-{i}", "unidadeOrgao": {"ufSigla": "CE"}} for i in range(20)],
        }

        async def get_page(params):
            if params["pagina"] == 1:
                return first_page
            if params["pagina"] == 2:
                raise RuntimeError("PNCP indisponível")
            return third_page

        with patch.object(licitacoes, "get_pncp_proposals", AsyncMock(side_effect=get_page)):
            total, items, complete, no_failures = await licitacoes.fetch_open(None, date(2026, 10, 6))

        self.assertEqual(total, 120)
        self.assertEqual(len(items), 70)
        self.assertFalse(complete)
        self.assertFalse(no_failures)

    async def test_open_notices_fetch_all_reported_pages(self):
        total_pages = 12
        total_records = total_pages * licitacoes.PAGE_SIZE

        async def get_page(params):
            page = params["pagina"]
            payload = {"data": [{"numeroControlePNCP": f"page-{page}-{i}", "unidadeOrgao": {"ufSigla": "CE"}} for i in range(licitacoes.PAGE_SIZE)]}
            if page == 1:
                payload.update({"totalRegistros": total_records, "totalPaginas": total_pages})
            return payload

        with patch.object(licitacoes, "get_pncp_proposals", AsyncMock(side_effect=get_page)) as pncp:
            total, items, complete, no_failures = await licitacoes.fetch_open(None, date(2026, 10, 6))

        self.assertEqual(total, total_records)
        self.assertEqual(len(items), total_records)
        self.assertEqual(pncp.await_count, total_pages)
        self.assertTrue(complete)
        self.assertTrue(no_failures)

    async def test_contract_collection_fetches_all_reported_pages(self):
        total_pages = 5

        async def get_page(params):
            page = params["pagina"]
            payload = {
                "data": [{"numeroControlePNCP": f"contract-{page}-{i}", "unidadeOrgao": {"ufSigla": "CE"}} for i in range(50)],
            }
            if page == 1:
                payload.update({"totalRegistros": total_pages * 50, "totalPaginas": total_pages})
            return payload

        with patch.object(licitacoes, "get_pncp_contracts", AsyncMock(side_effect=get_page)) as pncp:
            total, items, complete, no_failures = await licitacoes.collect(
                date(2026, 9, 1), date(2026, 9, 30), modalities=(6,),
            )

        self.assertEqual(total, total_pages * 50)
        self.assertEqual(len(items), total_pages * 50)
        self.assertEqual(pncp.await_count, total_pages)
        self.assertTrue(complete)
        self.assertTrue(no_failures)

    async def test_open_notices_retries_short_page_response(self):
        attempts = 0
        first_page = {
            "totalRegistros": 100, "totalPaginas": 2,
            "data": [{"numeroControlePNCP": f"first-{i}", "unidadeOrgao": {"ufSigla": "CE"}} for i in range(50)],
        }

        async def get_page(params):
            nonlocal attempts
            if params["pagina"] == 1:
                return first_page
            attempts += 1
            count = 1 if attempts == 1 else 50
            return {"data": [{"numeroControlePNCP": f"second-{i}", "unidadeOrgao": {"ufSigla": "CE"}} for i in range(count)]}

        with patch.object(licitacoes, "get_pncp_proposals", AsyncMock(side_effect=get_page)), patch.object(licitacoes.asyncio, "sleep", new_callable=AsyncMock):
            total, items, complete, no_failures = await licitacoes.fetch_open(None, date(2026, 10, 6))

        self.assertEqual(total, 100)
        self.assertEqual(len(items), 100)
        self.assertEqual(attempts, 2)
        self.assertTrue(complete)
        self.assertTrue(no_failures)

    async def test_open_notices_retries_short_first_page_response(self):
        total_pages = 12
        total_records = total_pages * licitacoes.PAGE_SIZE
        first_attempts = 0

        async def get_page(params):
            nonlocal first_attempts
            page = params["pagina"]
            count = licitacoes.PAGE_SIZE
            if page == 1:
                first_attempts += 1
                count = 1 if first_attempts == 1 else licitacoes.PAGE_SIZE
            payload = {
                "data": [{"numeroControlePNCP": f"page-{page}-{i}", "unidadeOrgao": {"ufSigla": "CE"}} for i in range(count)],
            }
            if page == 1:
                payload.update({"totalRegistros": total_records, "totalPaginas": total_pages})
            return payload

        with patch.object(licitacoes, "get_pncp_proposals", AsyncMock(side_effect=get_page)), patch.object(licitacoes.asyncio, "sleep", new_callable=AsyncMock):
            total, items, complete, no_failures = await licitacoes.fetch_open(None, date(2026, 10, 6))

        self.assertEqual(total, total_records)
        self.assertEqual(len(items), total_records)
        self.assertEqual(first_attempts, 2)
        self.assertTrue(complete)
        self.assertTrue(no_failures)

    async def test_short_cached_pncp_page_is_refetched_on_retry(self):
        params = {"pagina": 1, "tamanhoPagina": licitacoes.PAGE_SIZE}
        partial = {"totalRegistros": 50, "totalPaginas": 1, "data": [{"numeroControlePNCP": "partial"}]}
        complete = {"totalRegistros": 50, "totalPaginas": 1, "data": [{"numeroControlePNCP": f"item-{i}"} for i in range(50)]}
        client = FakeClient([FakeResponse(200, partial), FakeResponse(200, complete)])

        async def fetch_page(number, refresh=False):
            request_params = {**params, "pagina": number}
            if refresh:
                await extract.invalidate_pncp_proposal_page(request_params)
            return await extract.get_pncp_proposals(request_params)

        with patch("src.extract.httpx.AsyncClient", return_value=client), patch.object(licitacoes.asyncio, "sleep", new_callable=AsyncMock):
            result = await licitacoes._fetch_page_with_retries(fetch_page, 1)

        self.assertEqual(len(result["data"]), 50)
        self.assertEqual(client.calls, 2)

    async def test_open_notices_without_pagination_metadata_are_partial(self):
        response = {"data": [{"numeroControlePNCP": "ce-1", "unidadeOrgao": {"ufSigla": "CE"}}]}
        with patch.object(licitacoes, "get_pncp_proposals", AsyncMock(return_value=response)):
            total, items, complete, no_failures = await licitacoes.fetch_open(None, date(2026, 10, 6))

        self.assertEqual((total, len(items)), (1, 1))
        self.assertFalse(complete)
        self.assertTrue(no_failures)

    async def test_duplicate_records_across_pages_are_marked_partial(self):
        first_page = {
            "totalRegistros": 100, "totalPaginas": 2,
            "data": [{"numeroControlePNCP": f"item-{i}", "unidadeOrgao": {"ufSigla": "CE"}} for i in range(50)],
        }
        second_page = {
            "data": [{"numeroControlePNCP": f"item-{i}", "unidadeOrgao": {"ufSigla": "CE"}} for i in range(49)]
                    + [{"numeroControlePNCP": "item-49", "unidadeOrgao": {"ufSigla": "CE"}}],
        }
        with patch.object(licitacoes, "get_pncp_proposals", AsyncMock(side_effect=[first_page, second_page])):
            total, items, complete, no_failures = await licitacoes.fetch_open(None, date(2026, 10, 6))

        self.assertEqual(total, 100)
        self.assertEqual(len(items), 50)
        self.assertFalse(complete)
        self.assertTrue(no_failures)

    async def test_open_notices_accept_explicit_empty_response(self):
        response = {"totalPaginas": 0, "data": []}
        with patch.object(licitacoes, "get_pncp_proposals", AsyncMock(return_value=response)) as pncp:
            total, items, complete, no_failures = await licitacoes.fetch_open(None, date(2026, 10, 6))

        self.assertEqual((total, items), (0, []))
        self.assertEqual(pncp.await_count, 1)
        self.assertTrue(complete)
        self.assertTrue(no_failures)

    async def test_public_open_route_exposes_partial_status(self):
        item = {"numeroControlePNCP": "ce-1", "unidadeOrgao": {"ufSigla": "CE"}}
        with patch.object(pncp_sync, "fetch_open_cached", AsyncMock(return_value=(120, [item], False, False))):
            response = await api.public_open_notices(todos=True)

        self.assertEqual(response["total"], 120)
        self.assertTrue(response["amostra_limitada"])
        self.assertFalse(response["consulta_completa"])

    async def test_public_open_route_reports_exhausted_page_retries(self):
        with patch.object(pncp_sync, "fetch_open_cached", AsyncMock(side_effect=RuntimeError("Página incompleta"))):
            with self.assertRaises(HTTPException) as raised:
                await api.public_open_notices()

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("todas as páginas", raised.exception.detail)

    async def test_municipality_route_reports_exhausted_open_page_retries(self):
        with patch.object(pncp_sync, "fetch_open_cached", AsyncMock(side_effect=RuntimeError("Página incompleta"))), patch.object(
            licitacoes, "collect", AsyncMock(return_value=(0, [], True, True)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await api.municipality_notices("2304400", "2026-09-01", "2026-09-30")

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("todas as páginas", raised.exception.detail)

    async def test_open_snapshot_is_served_from_database_until_due(self):
        item = {"numeroControlePNCP": "open-1", "unidadeOrgao": {"ufSigla": "CE"}}
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with patch.object(pncp_sync, "get_db", MagicMock(return_value=object())), patch.object(
            pncp_sync, "get_pncp_open_sync_state", MagicMock(return_value={"status": "complete", "last_started_at": recent}),
        ), patch.object(
            pncp_sync, "load_pncp_open_snapshot", MagicMock(return_value=[{"raw_data": item}]),
        ), patch.object(pncp_sync.licitacoes, "fetch_open", AsyncMock()) as fetch:
            total, items, complete, no_failures = await pncp_sync.fetch_open_cached(None, date.today())

        self.assertEqual((total, len(items)), (1, 1))
        self.assertTrue(complete)
        self.assertTrue(no_failures)
        fetch.assert_not_awaited()

    async def test_open_snapshot_refreshes_after_twelve_hours(self):
        item = {"numeroControlePNCP": "open-1", "unidadeOrgao": {"ufSigla": "CE"}}
        stale = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        with patch.object(pncp_sync, "get_db", MagicMock(return_value=object())), patch.object(
            pncp_sync, "get_pncp_open_sync_state", MagicMock(return_value={"status": "complete", "last_started_at": stale}),
        ), patch.object(
            pncp_sync, "update_pncp_open_sync_state", MagicMock(),
        ), patch.object(
            pncp_sync.licitacoes, "fetch_open", AsyncMock(return_value=(1, [item], True, True)),
        ) as fetch, patch.object(
            pncp_sync, "save_pncp_open_snapshot", MagicMock(return_value=True),
        ), patch.object(
            pncp_sync, "load_pncp_open_snapshot", MagicMock(return_value=[{"raw_data": item}]),
        ):
            total, items, complete, no_failures = await pncp_sync.fetch_open_cached(None, date.today())

        fetch.assert_awaited_once()
        self.assertEqual((total, len(items)), (1, 1))
        self.assertTrue(complete)
        self.assertTrue(no_failures)

    async def test_failed_open_snapshot_refresh_serves_still_valid_cached_notices(self):
        item = {"numeroControlePNCP": "open-cached", "unidadeOrgao": {"ufSigla": "CE"}}
        stale = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        with patch.object(pncp_sync, "get_db", MagicMock(return_value=object())), patch.object(
            pncp_sync, "get_pncp_open_sync_state", MagicMock(return_value={"status": "complete", "last_started_at": stale}),
        ), patch.object(pncp_sync, "update_pncp_open_sync_state", MagicMock()), patch.object(
            pncp_sync.licitacoes, "fetch_open", AsyncMock(side_effect=RuntimeError("PNCP indisponível")),
        ), patch.object(
            pncp_sync, "load_pncp_open_snapshot", MagicMock(return_value=[{"raw_data": item}]),
        ):
            total, items, complete, no_failures = await pncp_sync.fetch_open_cached(None, date.today())

        self.assertEqual((total, items), (1, [item]))
        self.assertFalse(complete)
        self.assertFalse(no_failures)


if __name__ == "__main__":
    unittest.main()
