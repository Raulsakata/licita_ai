const DEFAULT_BASE_URL = 'https://pncp.gov.br/api/consulta/v1';

export async function consultarContratacoes({ dataInicial, dataFinal, codigoModalidadeContratacao, pagina, tamanhoPagina }) {
  const baseUrl = process.env.PNCP_BASE_URL || DEFAULT_BASE_URL;
  const query = new URLSearchParams({ dataInicial, dataFinal, pagina: String(pagina), tamanhoPagina: String(tamanhoPagina) });
  if (codigoModalidadeContratacao) query.set('codigoModalidadeContratacao', String(codigoModalidadeContratacao));

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12_000);
  try {
    const response = await fetch(`${baseUrl}/contratacoes/publicacao?${query}`, {
      headers: { accept: 'application/json' }, signal: controller.signal
    });
    if (!response.ok) throw new Error(`PNCP respondeu ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

