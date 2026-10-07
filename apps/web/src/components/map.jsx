import { useEffect, useMemo, useRef, useState } from 'react';
import { brlCompact, num, useFetch } from '../lib/api';
import NoticeExplorer from './explorer';
import { Card, Filters, Notice, NoticeCard, PriorityNotice, Tabs, defaultFilters, toRange } from './ui';

const normalize = (text) => String(text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();

function projectMesh(geo) {
  const rings = (geometry) => (geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates).flat();
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  geo.features.forEach((feature) => rings(feature.geometry).forEach((ring) => ring.forEach(([lon, lat]) => {
    minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon); minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
  })));
  const k = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
  const scale = 700 / Math.max((maxLon - minLon) * k, maxLat - minLat);
  const width = (maxLon - minLon) * k * scale, height = (maxLat - minLat) * scale;
  const features = geo.features.map((feature) => ({
    code: feature.properties.codarea,
    d: rings(feature.geometry).map((ring) => `M${ring.map(([lon, lat]) => `${((lon - minLon) * k * scale).toFixed(1)},${((maxLat - lat) * scale).toFixed(1)}`).join('L')}Z`).join(''),
  }));
  return { features, width, height };
}

export function CearaMap({ summary, selected, onSelect }) {
  const mesh = useFetch('/api/geografia/mapa', {});
  const cities = useFetch('/api/geografia/municipios', {});
  const [hover, setHover] = useState(null);
  const [metric, setMetric] = useState('quantidade');
  const box = useRef(null);
  const projected = useMemo(() => (mesh.data ? projectMesh(mesh.data) : null), [mesh.data]);
  const names = useMemo(() => Object.fromEntries((cities.data || []).map((city) => [String(city.id), city.nome])), [cities.data]);
  const stats = useMemo(() => Object.fromEntries((summary?.por_municipio || []).map((row) => [normalize(row.municipio), row])), [summary]);
  const max = Math.max(1, ...(summary?.por_municipio || []).map((row) => row[metric]));
  const statFor = (code) => stats[normalize(names[code])];
  const fill = (code) => { const row = statFor(code); return row ? `rgba(198,107,36,${(0.18 + 0.82 * Math.sqrt(row[metric] / max)).toFixed(2)})` : '#e9edf1'; };
  const track = (event, code) => {
    const rect = box.current.getBoundingClientRect();
    setHover({ code, x: event.clientX - rect.left, y: event.clientY - rect.top });
  };
  const hoverRow = hover && statFor(hover.code);
  return (
    <Card title="Mapa interativo do Ceará" aside={<div className="row-gap"><span className="muted">Passe o mouse para ver o município; clique para detalhar</span><div className="tabs"><button type="button" className={metric === 'quantidade' ? 'on' : ''} onClick={() => setMetric('quantidade')}>Quantidade</button><button type="button" className={metric === 'valor' ? 'on' : ''} onClick={() => setMetric('valor')}>Valor</button></div></div>}>
      <Notice error={mesh.error} />
      <div className="map-box" ref={box}>
        {!projected ? <p className="empty">{mesh.loading ? 'Carregando mapa…' : 'Mapa indisponível.'}</p> : (
          <svg viewBox={`0 0 ${projected.width} ${projected.height}`} role="group" aria-label="Mapa dos municípios do Ceará">
            {projected.features.map((feature) => (
              <path key={feature.code} d={feature.d} className={`muni ${selected === feature.code ? 'sel' : ''}`} style={{ fill: fill(feature.code) }}
                tabIndex={0} role="button" aria-label={names[feature.code] || feature.code}
                onMouseMove={(e) => track(e, feature.code)} onMouseLeave={() => setHover(null)}
                onFocus={(e) => { const r = e.target.getBoundingClientRect(); const b = box.current.getBoundingClientRect(); setHover({ code: feature.code, x: r.left - b.left + r.width / 2, y: r.top - b.top }); }} onBlur={() => setHover(null)}
                onClick={() => onSelect(feature.code, names[feature.code])} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(feature.code, names[feature.code]); } }} />
            ))}
          </svg>
        )}
        {hover && <div className="map-tip" style={{ left: hover.x + 12, top: hover.y + 12 }}><strong>{names[hover.code] || hover.code}</strong>{hoverRow ? <span>{num(hoverRow.quantidade)} licitações · {brlCompact(hoverRow.valor)}</span> : <span>Sem licitações no filtro</span>}</div>}
      </div>
      <div className="map-legend"><span>Menos</span><i /><span>Mais ({metric === 'valor' ? 'valor' : 'licitações'})</span></div>
    </Card>
  );
}

export function MunicipalityPanel({ code, name, onClose }) {
  const [filters, setFilters] = useState(() => ({ ...defaultFilters(), inicio: new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10) }));
  const [tab, setTab] = useState('abertas');
  const [text, setText] = useState('');
  const ref = useRef(null);
  const { data, loading, error } = useFetch(`/api/publico/municipio/${code}/licitacoes`, toRange(filters));
  useEffect(() => { ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, [code]);
  const list = (data?.[tab] || []).filter((item) => `${item.objeto} ${item.orgao}`.toLowerCase().includes(text.toLowerCase()));
  return (
    <div ref={ref}>
      <Card title={`${name || code} — licitações`} className="muni-panel" aside={<button type="button" className="chip" onClick={onClose}>Fechar ✕</button>}>
        <PriorityNotice />
        <p className="muted">Abertas: vigentes hoje. Encerradas: com prazo de propostas já vencido, dentro do período selecionado.</p>
        <Filters filters={filters} onChange={setFilters} hideCity />
        <Notice error={error} partial={data?.amostra_limitada} incomplete={data && !data.consulta_completa} />
        <div className="row-gap">
          <Tabs value={tab} onChange={setTab} options={[['abertas', `Abertas (${data ? num(data.abertas_total) : '…'})`], ['encerradas', `Encerradas (${data ? num(data.encerradas_total) : '…'})`]]} />
          <input className="search" type="search" placeholder="Buscar por objeto ou órgão…" value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <div className="notice-grid" style={{ opacity: loading ? 0.5 : 1 }}>{list.map((item) => <NoticeCard key={item.id} item={item} showStatus={false} />)}</div>
        {!loading && data && !list.length && <p className="empty">Nenhuma licitação {tab === 'abertas' ? 'aberta' : 'encerrada'} para este município e período.</p>}
        {loading && !data && <p className="empty">Carregando licitações…</p>}
      </Card>
    </div>
  );
}

export function OpenNoticesDialog({ municipio, scope, mpeOnly, onClose, initialText = '' }) {
  const { data, loading, error } = useFetch('/api/publico/abertos', { municipio, todos: 1, somente_mpe: mpeOnly ? 1 : '' });
  const [text, setText] = useState(initialText);
  useEffect(() => { const onKey = (e) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, [onClose]);
  const list = (data?.editais || []).filter((item) => `${item.objeto} ${item.orgao} ${item.municipio}`.toLowerCase().includes(text.toLowerCase()));
  return (
    <div className="overlay" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label="Licitações abertas" onClick={(e) => e.stopPropagation()}>
        <header className="card-head"><h2>Licitações vigentes abertas — {scope}</h2><button type="button" className="chip" onClick={onClose}>Fechar ✕</button></header>
        <input className="search" type="search" autoFocus placeholder="Buscar por objeto, órgão ou município…" value={text} onChange={(e) => setText(e.target.value)} />
        {mpeOnly && <PriorityNotice />}
        <p className="muted" aria-live="polite">{loading ? 'Carregando todas as licitações abertas…' : `${num(list.length)} exibida(s) de ${num(data?.total)} abertas no total`}</p>
        <Notice error={error} partial={data?.amostra_limitada} incomplete={data && !data.consulta_completa} />
        <NoticeExplorer items={list} />
      </div>
    </div>
  );
}
