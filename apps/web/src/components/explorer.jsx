import { useMemo, useState } from 'react';
import { num } from '../lib/api';
import { daysLeft, exportCsv } from '../lib/tools';
import { NoticeCard } from './ui';

const SORTS = {
  prazo: (a, b) => (new Date(a.encerramento_propostas || 8.64e15) - new Date(b.encerramento_propostas || 8.64e15)),
  maior: (a, b) => b.valor - a.valor,
  menor: (a, b) => a.valor - b.valor,
};

// Filtros por valor, modalidade e prazo + ordenação + exportação (CSV e PDF via impressão).
export default function NoticeExplorer({ items, pageSize = 30 }) {
  const [min, setMin] = useState('');
  const [max, setMax] = useState('');
  const [modalidade, setModalidade] = useState('');
  const [prazo, setPrazo] = useState('');
  const [sort, setSort] = useState('prazo');
  const [shown, setShown] = useState(pageSize);
  const modalities = useMemo(() => [...new Set(items.map((i) => i.modalidade).filter(Boolean))].sort(), [items]);
  const list = useMemo(() => items
    .filter((i) => (!min || i.valor >= Number(min)) && (!max || i.valor <= Number(max)))
    .filter((i) => !modalidade || i.modalidade === modalidade)
    .filter((i) => { if (!prazo) return true; const d = daysLeft(i.encerramento_propostas); return d != null && d <= Number(prazo); })
    .sort(SORTS[sort]), [items, min, max, modalidade, prazo, sort]);
  return (
    <div className="explorer">
      <div className="filters no-print">
        <label>Valor mínimo (R$)<input type="number" min="0" value={min} onChange={(e) => { setMin(e.target.value); setShown(pageSize); }} /></label>
        <label>Valor máximo (R$)<input type="number" min="0" value={max} onChange={(e) => { setMax(e.target.value); setShown(pageSize); }} /></label>
        <label>Modalidade<select value={modalidade} onChange={(e) => { setModalidade(e.target.value); setShown(pageSize); }}><option value="">Todas</option>{modalities.map((m) => <option key={m}>{m}</option>)}</select></label>
        <label>Prazo<select value={prazo} onChange={(e) => { setPrazo(e.target.value); setShown(pageSize); }}><option value="">Qualquer</option><option value="3">Vence em até 3 dias</option><option value="7">Até 7 dias</option><option value="15">Até 15 dias</option></select></label>
        <label>Ordenar por<select value={sort} onChange={(e) => setSort(e.target.value)}><option value="prazo">Encerramento mais próximo</option><option value="maior">Maior valor</option><option value="menor">Menor valor</option></select></label>
        <div className="row-gap"><button type="button" className="chip" onClick={() => exportCsv(list)}>⬇ Excel (CSV)</button><button type="button" className="chip" onClick={() => window.print()}>🖨 PDF</button></div>
      </div>
      <p className="muted">{num(list.length)} edital(is) encontrado(s)</p>
      <div className="notice-grid">{list.slice(0, shown).map((item) => <NoticeCard key={item.id} item={item} showStatus={false} />)}</div>
      {shown < list.length && <button type="button" className="chip no-print" onClick={() => setShown(shown + pageSize)}>Mostrar mais ({num(list.length - shown)} restantes)</button>}
      {!list.length && <p className="empty">Nenhum edital para estes filtros.</p>}
    </div>
  );
}
