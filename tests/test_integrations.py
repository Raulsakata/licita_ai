import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import HTTPException

import src.api as api
import src.auth as auth
import src.cnae as cnae
import src.licitacoes as licitacoes
import src.db as db
import src.extract as extract
from src.schemas import Eligibility
from src.transform import assess_eligibility


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
        with patch.object(licitacoes, "get_pncp_contracts", pncp), patch.object(api, "save_pncp_results", MagicMock()):
            summary = await api.public_summary(None, "2026-09-01", "2026-09-30")
        params = [call.args[0] for call in pncp.await_args_list]
        self.assertTrue(all(p["uf"] == "CE" for p in params))
        self.assertEqual(summary["quantidade_amostra"], 1)
        self.assertEqual(summary["valor_total"], 1250)
        self.assertEqual(summary["por_municipio"][0]["municipio"], "Fortaleza")

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
        with patch.object(api, "get_company", MagicMock(return_value=row)), patch.object(licitacoes, "get_pncp_contracts", pncp):
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


if __name__ == "__main__":
    unittest.main()
