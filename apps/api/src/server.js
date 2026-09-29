import 'dotenv/config';
import cors from 'cors';
import express from 'express';
import { z } from 'zod';
import { consultarContratacoes } from './services/pncp.js';
import { getSupabase } from './services/supabase.js';

const app = express();
const port = Number(process.env.PORT || 3000);
const allowedOrigins = (process.env.FRONTEND_ORIGIN || 'http://localhost:5173').split(',').map((value) => value.trim());

app.use(cors({ origin: allowedOrigins }));
app.use(express.json());

app.get('/health', async (_request, response) => {
  const supabase = await getSupabase();
  response.status(200).json({ status: 'ok', integrations: { pncp: 'configured', supabase: supabase ? 'configured' : 'pending' } });
});

const filtersSchema = z.object({
  dataInicial: z.string().regex(/^\d{8}$/, 'Use AAAAMMDD'),
  dataFinal: z.string().regex(/^\d{8}$/, 'Use AAAAMMDD'),
  codigoModalidadeContratacao: z.coerce.number().int().positive().optional(),
  pagina: z.coerce.number().int().positive().default(1),
  tamanhoPagina: z.coerce.number().int().min(1).max(50).default(10)
}).refine((values) => values.dataInicial <= values.dataFinal, { message: 'A data inicial deve ser anterior à final' });

app.get('/api/pncp/contratacoes', async (request, response, next) => {
  const parsed = filtersSchema.safeParse(request.query);
  if (!parsed.success) return response.status(400).json({ error: 'Filtros inválidos', details: parsed.error.flatten() });
  try {
    const data = await consultarContratacoes(parsed.data);
    return response.json(data);
  } catch (error) {
    return next(error);
  }
});

app.use((error, _request, response, _next) => {
  console.error(error);
  response.status(502).json({ error: 'Não foi possível consultar o PNCP neste momento.' });
});

app.listen(port, () => console.log(`API disponível na porta ${port}`));
