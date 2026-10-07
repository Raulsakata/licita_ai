import { useMemo, useState } from 'react';
import { brl, brlCompact, fmtDate, num } from '../lib/api';
import { Card, Stat } from './ui';
import { daysLeft } from '../lib/tools';

const DemoBadge = () => <span className="badge demo">Demonstração · dados fictícios</span>;
const DAY = 86400000;
const avg = (list) => (list.length ? list.reduce((a, b) => a + b, 0) / list.length : null);

// Número estável (20–90) derivado do nome do órgão, para a demonstração não mudar a cada acesso.
const seeded = (text, min, max) => {
  let h = 0;
  for (const ch of String(text)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return min + (h % (max - min + 1));
};

function group(items, key) {
  const map = new Map();
  items.forEach((item) => {
    const name = item[key] || 'Não informado';
    const row = map.get(name) || { nome: name, quantidade: 0, valor: 0 };
    row.quantidade += 1; row.valor += Number(item.valor || 0);
    map.set(name, row);
  });
  return [...map.values()].sort((a, b) => b.quantidade - a.quantidade);
}

function Ranking({ rows, label }) {
  const max = Math.max(1, ...rows.map((r) => r.quantidade));
  return (
    <ul className="rank-list">
      {rows.map((r) => (
        <li key={r.nome}><span className="name" title={r.nome}>{r.nome}</span><span className="track"><i style={{ width: `${(r.quantidade / max) * 100}%` }} /></span><span className="val">{num(r.quantidade)} {label} · {brlCompact(r.valor)}</span></li>
      ))}
    </ul>
  );
}

function Payment({ organs }) {
  const rows = organs.slice(0, 6).map((o) => ({ ...o, prazo: seeded(o.nome, 18, 75), pontual: seeded(`${o.nome}!`, 55, 98) }));
  const media = Math.round(avg(rows.map((r) => r.prazo)) || 0);
  return (
    <Card title="Prazo médio de pagamento dos órgãos (licitações encerradas)" aside={<DemoBadge />}>
      <p className="muted">O PNCP não informa quando o pagamento foi efetivado. Em uma versão futura este indicador viria dos portais de transparência (custo de integração), por isso os números abaixo são ilustrativos.</p>
      <div className="stats"><Stat label="Prazo médio de pagamento" value={`${media} dias`} /><Stat label="Pagamentos no prazo (média)" value={`${Math.round(avg(rows.map((r) => r.pontual)) || 0)}%`} tone="good" /></div>
      <table className="table"><thead><tr><th>Órgão</th><th>Prazo médio</th><th>Pagou no prazo</th><th>Risco</th></tr></thead><tbody>
        {rows.map((r) => <tr key={r.nome}><td>{r.nome}</td><td>{r.prazo} dias</td><td>{r.pontual}%</td><td><span className={`status-pill ${r.prazo <= 30 ? 'good' : r.prazo <= 50 ? '' : 'bad'}`}>{r.prazo <= 30 ? 'Baixo' : r.prazo <= 50 ? 'Médio' : 'Alto'}</span></td></tr>)}
      </tbody></table>
    </Card>
  );
}

const DOCS = ['Certidão negativa federal (RFB/PGFN)', 'Certidão negativa estadual (SEFAZ-CE)', 'Certidão negativa municipal', 'Certificado de regularidade do FGTS (CRF)', 'Certidão negativa trabalhista (CNDT)', 'Contrato social / requerimento de empresário', 'Balanço patrimonial do último exercício', 'Atestado de capacidade técnica', 'Declaração de ME/EPP (Simples Nacional)'];

function Checklist() {
  const [done, setDone] = useState(() => { try { return JSON.parse(localStorage.getItem('licita.docs')) || {}; } catch { return {}; } });
  const toggle = (doc) => { const next = { ...done, [doc]: !done[doc] }; setDone(next); localStorage.setItem('licita.docs', JSON.stringify(next)); };
  const total = DOCS.filter((d) => done[d]).length;
  return (
    <Card title="Checklist de documentos de habilitação" aside={<span className="muted">{total}/{DOCS.length} prontos · salvo neste navegador</span>}>
      <div className="progress"><i style={{ width: `${(total / DOCS.length) * 100}%` }} /></div>
      <ul className="checklist">{DOCS.map((doc) => <li key={doc}><label className="check"><input type="checkbox" checked={Boolean(done[doc])} onChange={() => toggle(doc)} /> {doc}</label></li>)}</ul>
    </Card>
  );
}

function Simulator({ avgValue }) {
  const [cost, setCost] = useState('');
  const [margin, setMargin] = useState(15);
  const [tax, setTax] = useState(6);
  const base = Number(cost) || 0;
  const price = base / (1 - (Number(margin) + Number(tax)) / 100);
  const ok = base > 0 && Number(margin) + Number(tax) < 100;
  return (
    <Card title="Simulador de proposta">
      <div className="filters">
        <label>Custo total (R$)<input type="number" min="0" value={cost} onChange={(e) => setCost(e.target.value)} placeholder="Ex.: 85000" /></label>
        <label>Margem desejada (%)<input type="number" min="0" max="90" value={margin} onChange={(e) => setMargin(e.target.value)} /></label>
        <label>Impostos (%)<input type="number" min="0" max="50" value={tax} onChange={(e) => setTax(e.target.value)} /></label>
      </div>
      {ok ? <p className="notice ok"><b>Preço mínimo sugerido: {brl(price)}</b> · lucro estimado {brl(price * (margin / 100))}{avgValue ? ` · valor médio dos editais compatíveis: ${brlCompact(avgValue)}` : ''}</p> : <p className="muted">Informe o custo para calcular o preço mínimo da proposta.</p>}
    </Card>
  );
}

export default function CompanyInsights({ items }) {
  const stats = useMemo(() => {
    const now = Date.now();
    const closed = items.filter((i) => i.encerramento_propostas && new Date(i.encerramento_propostas).getTime() <= now);
    const open = items.filter((i) => !i.encerramento_propostas || new Date(i.encerramento_propostas).getTime() > now);
    const spans = items.filter((i) => i.publicacao && i.encerramento_propostas).map((i) => (new Date(i.encerramento_propostas) - new Date(i.publicacao)) / DAY).filter((d) => d >= 0 && d < 365);
    const values = items.map((i) => Number(i.valor || 0)).filter(Boolean);
    const next = open.filter((i) => daysLeft(i.encerramento_propostas) != null).sort((a, b) => new Date(a.encerramento_propostas) - new Date(b.encerramento_propostas));
    return {
      closed: closed.length, open: open.length, span: avg(spans), avgValue: avg(values), total: values.reduce((a, b) => a + b, 0),
      week: next.filter((i) => daysLeft(i.encerramento_propostas) <= 7).length, next: next.slice(0, 5),
      organs: group(items, 'orgao'), cities: group(items, 'municipio'), modalities: group(items, 'modalidade'),
    };
  }, [items]);
  if (!items.length) return null;
  return (
    <>
      <div className="stats">
        <Stat label="Valor total das oportunidades" value={brlCompact(stats.total)} tone="accent" />
        <Stat label="Valor médio por edital" value={brlCompact(stats.avgValue)} />
        <Stat label="Duração média da disputa" value={stats.span == null ? '—' : `${stats.span.toFixed(1)} dias`} hint="publicação até encerramento das propostas" />
        <Stat label="Já encerradas (histórico)" value={num(stats.closed)} />
        <Stat label="Encerram em até 7 dias" value={num(stats.week)} tone={stats.week ? 'bad' : ''} />
      </div>
      <div className="grid-2">
        <Card title="Próximos prazos">
          {stats.next.length ? <ul className="deadline-list">{stats.next.map((i) => <li key={i.id}><b>{daysLeft(i.encerramento_propostas)} dia(s)</b><span>{(i.objeto || '').slice(0, 90)} — {i.municipio}</span><small>{fmtDate(i.encerramento_propostas)}</small></li>)}</ul> : <p className="empty">Nenhum prazo em aberto.</p>}
        </Card>
        <Card title="Modalidades mais frequentes"><Ranking rows={stats.modalities.slice(0, 5)} label="edital(is)" /></Card>
        <Card title="Órgãos que mais licitam no seu ramo"><Ranking rows={stats.organs.slice(0, 6)} label="edital(is)" /></Card>
        <Card title="Municípios com mais oportunidades"><Ranking rows={stats.cities.slice(0, 6)} label="edital(is)" /></Card>
      </div>
      <Payment organs={stats.organs} />
      <div className="grid-2"><Simulator avgValue={stats.avgValue} /><Checklist /></div>
    </>
  );
}
