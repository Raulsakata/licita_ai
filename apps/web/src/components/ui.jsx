import { useMemo, useState } from 'react';
import { brl, brlCompact, num, useFetch } from '../lib/api';

export function Stat({ label, value, hint, tone, loading }) {
  return <div className={`stat ${tone || ''} ${loading ? 'is-loading' : ''}`}><span>{label}</span><strong>{loading ? '…' : value}</strong>{hint && <small>{hint}</small>}</div>;
}

export function Notice({ error, partial }) {
  if (error) return <div className="notice error" role="alert">{error}</div>;
  if (partial) return <div className="notice">Dados do PNCP obtidos por amostragem: totais de quantidade são exatos; valores consideram os editais carregados.</div>;
  return null;
}

export function Card({ title, aside, children, className = '' }) {
  return <section className={`card ${className}`}><header className="card-head"><h2>{title}</h2>{aside}</header>{children}</section>;
}

export function Tabs({ value, onChange, options }) {
  return <div className="tabs" role="tablist">{options.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={value === id} className={value === id ? 'on' : ''} onClick={() => onChange(id)}>{label}</button>)}</div>;
}

const todayIso = () => new Date().toISOString().slice(0, 10);
const daysAgo = (days) => new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
const currentYear = new Date().getFullYear();

export const defaultFilters = () => ({ municipio: '', modo: 'datas', inicio: daysAgo(30), fim: todayIso(), ano: String(currentYear) });

export function toRange(filters) {
  if (filters.modo === 'ano') {
    const end = Number(filters.ano) === currentYear ? todayIso() : `${filters.ano}-12-31`;
    return { inicio: `${filters.ano}-01-01`, fim: end };
  }
  return { inicio: filters.inicio, fim: filters.fim };
}

export function Filters({ filters, onChange }) {
  const { data: cities } = useFetch('/api/geografia/municipios', {});
  const set = (patch) => onChange({ ...filters, ...patch });
  const years = Array.from({ length: 6 }, (_, i) => String(currentYear - i));
  const presets = [['30 dias', 30], ['90 dias', 90], ['6 meses', 180]];
  return (
    <div className="filters" role="search">
      <label>Município (CE)
        <select value={filters.municipio} onChange={(e) => set({ municipio: e.target.value })}>
          <option value="">Todo o Ceará</option>
          {(cities || []).map((city) => <option key={city.id} value={city.id}>{city.nome}</option>)}
        </select>
      </label>
      <label>Período por
        <select value={filters.modo} onChange={(e) => set({ modo: e.target.value })}><option value="datas">Datas</option><option value="ano">Ano</option></select>
      </label>
      {filters.modo === 'ano'
        ? <label>Ano<select value={filters.ano} onChange={(e) => set({ ano: e.target.value })}>{years.map((y) => <option key={y}>{y}</option>)}</select></label>
        : <>
          <label>De<input type="date" value={filters.inicio} max={filters.fim} onChange={(e) => set({ inicio: e.target.value })} /></label>
          <label>Até<input type="date" value={filters.fim} min={filters.inicio} max={todayIso()} onChange={(e) => set({ fim: e.target.value })} /></label>
        </>}
      {filters.modo === 'datas' && <div className="presets">{presets.map(([label, days]) => <button key={label} type="button" className="chip" onClick={() => set({ inicio: daysAgo(days), fim: todayIso() })}>{label}</button>)}</div>}
      <button type="button" className="chip ghost" onClick={() => onChange(defaultFilters())}>Limpar</button>
    </div>
  );
}

export function ColumnChart({ rows, labelKey, title }) {
  const [metric, setMetric] = useState('quantidade');
  const [hover, setHover] = useState(null);
  const max = Math.max(1, ...rows.map((row) => row[metric]));
  const format = metric === 'valor' ? brlCompact : num;
  if (!rows.length) return <p className="empty">Sem dados para o filtro atual.</p>;
  return (
    <div className="column-chart">
      <div className="chart-bar-head"><Tabs value={metric} onChange={setMetric} options={[['quantidade', 'Quantidade'], ['valor', 'Valor (R$)']]} /><span className="hover-info" aria-live="polite">{hover != null ? `${rows[hover][labelKey]}: ${metric === 'valor' ? brl(rows[hover].valor) : num(rows[hover].quantidade)}` : title}</span></div>
      <svg viewBox={`0 0 ${rows.length * 48 + 20} 190`} role="img" aria-label={title} preserveAspectRatio="xMidYMid meet">
        {rows.map((row, index) => {
          const height = (row[metric] / max) * 130;
          return (
            <g key={row[labelKey]} onMouseEnter={() => setHover(index)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(index)} onBlur={() => setHover(null)} tabIndex={0}>
              <rect className={hover === index ? 'col hot' : 'col'} x={index * 48 + 14} y={150 - height} width="34" height={Math.max(height, 2)} rx="4"><title>{`${row[labelKey]}: ${format(row[metric])}`}</title></rect>
              <text x={index * 48 + 31} y={144 - height} textAnchor="middle" className="col-value">{format(row[metric])}</text>
              <text x={index * 48 + 31} y="172" textAnchor="middle" className="col-label">{String(row[labelKey]).slice(-5)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function BarList({ rows, labelKey, metric = 'valor', limit = 8, onSelect, selected }) {
  const [metricState, setMetric] = useState(metric);
  const top = useMemo(() => [...rows].sort((a, b) => b[metricState] - a[metricState]).slice(0, limit), [rows, metricState, limit]);
  const max = Math.max(1, ...top.map((row) => row[metricState]));
  if (!rows.length) return <p className="empty">Sem dados para o filtro atual.</p>;
  return (
    <div className="bar-list">
      <Tabs value={metricState} onChange={setMetric} options={[['valor', 'Valor'], ['quantidade', 'Quantidade']]} />
      <ul>
        {top.map((row) => (
          <li key={row[labelKey]}>
            <button type="button" className={selected === row[labelKey] ? 'on' : ''} onClick={() => onSelect?.(row[labelKey])} disabled={!onSelect} title={onSelect ? 'Filtrar por este item' : undefined}>
              <span className="name">{row[labelKey]}</span>
              <span className="track"><i style={{ width: `${(row[metricState] / max) * 100}%` }} /></span>
              <span className="val">{metricState === 'valor' ? brlCompact(row.valor) : num(row.quantidade)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function CityTable({ rows }) {
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState({ key: 'valor', dir: -1 });
  const filtered = rows.filter((row) => row.municipio.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => (typeof a[sort.key] === 'string' ? a[sort.key].localeCompare(b[sort.key]) : a[sort.key] - b[sort.key]) * sort.dir);
  const head = (key, label) => <th><button type="button" onClick={() => setSort((s) => ({ key, dir: s.key === key ? -s.dir : -1 }))}>{label}{sort.key === key ? (sort.dir > 0 ? ' ▲' : ' ▼') : ''}</button></th>;
  return (
    <div className="table-wrap">
      <input className="search" type="search" placeholder="Buscar município…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <div className="scroll"><table><thead><tr>{head('municipio', 'Município')}{head('quantidade', 'Licitações')}{head('valor', 'Valor estimado')}</tr></thead>
        <tbody>{filtered.map((row) => <tr key={row.municipio}><td>{row.municipio}</td><td>{num(row.quantidade)}</td><td>{brl(row.valor)}</td></tr>)}
          {!filtered.length && <tr><td colSpan="3" className="empty">Nenhum município encontrado.</td></tr>}</tbody></table></div>
    </div>
  );
}

export function NoticeCard({ item, locked, showStatus = true }) {
  const [open, setOpen] = useState(false);
  const closing = item.encerramento_propostas ? new Date(item.encerramento_propostas) : null;
  const isOpen = closing && closing > new Date();
  return (
    <article className={`notice-card ${locked ? 'locked' : ''}`}>
      <header>
        {showStatus && <span className={`badge ${locked ? 'bad' : 'good'}`}>{locked ? '🔒 Não Apta' : 'Apta'}</span>}
        {item.exige_porte_me_epp && <span className="badge">Exigência ME/EPP</span>}
        <span className={`badge ${isOpen ? 'good' : ''}`}>{isOpen ? 'Propostas abertas' : 'Fora do prazo / sem prazo'}</span>
      </header>
      <h3>{item.objeto || 'Objeto não informado'}</h3>
      <p className="meta">{item.orgao} · {item.municipio || 'CE'} · {item.modalidade}</p>
      <div className="facts"><span>Valor: <b>{item.valor ? brl(item.valor) : 'Sigiloso/N/I'}</b></span><span>Abertura: <b>{item.abertura_propostas ? new Date(item.abertura_propostas).toLocaleString('pt-BR') : '—'}</b></span><span>Encerramento: <b>{closing ? closing.toLocaleString('pt-BR') : '—'}</b></span></div>
      {locked && <p className="restriction">{item.motivo}</p>}
      <button type="button" className="link" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? 'Ocultar detalhes' : 'Ver detalhes'}</button>
      {open && <dl>
        <dt>Nº / Processo</dt><dd>{item.numero || '—'} / {item.processo || '—'}</dd>
        <dt>Publicação</dt><dd>{item.publicacao ? new Date(item.publicacao).toLocaleDateString('pt-BR') : '—'}</dd>
        <dt>Situação</dt><dd>{item.situacao || '—'}</dd>
        {item.informacao_complementar && <><dt>Informação complementar</dt><dd>{item.informacao_complementar}</dd></>}
      </dl>}
      <footer>{item.link_edital && <a href={item.link_edital} target="_blank" rel="noopener noreferrer">Edital no PNCP ↗</a>}{item.link_origem && <a href={item.link_origem} target="_blank" rel="noopener noreferrer">Sistema de origem ↗</a>}</footer>
    </article>
  );
}
