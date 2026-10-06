import { useState } from 'react';
import { brl, brlCompact, num, pct, useFetch } from '../lib/api';
import { BarList, Card, CityTable, ColumnChart, Filters, Notice, NoticeCard, Stat, Tabs, defaultFilters, toRange } from '../components/ui';
import { CearaMap, MunicipalityPanel, OpenNoticesDialog } from '../components/map';

function MpeComparison({ params }) {
  const [metric, setMetric] = useState('quantidade_mpe');
  const [years, setYears] = useState('3');
  const { data, loading, error } = useFetch('/api/publico/comparativo-mpe', { ...params, anos: years });
  const rows = data?.anos || [];
  const max = Math.max(1, ...rows.map((row) => row[metric]));
  const variation = metric === 'valor_mpe' ? 'variacao_valor_mpe' : 'variacao_quantidade_mpe';
  return (
    <Card title="Comparativo histórico — Micro e Pequenas Empresas" className="mpe" aside={<div className="row-gap"><Tabs value={metric} onChange={setMetric} options={[['quantidade_mpe', 'Quantidade'], ['valor_mpe', 'Valor']]} /><select aria-label="Anos anteriores" value={years} onChange={(e) => setYears(e.target.value)}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} ano(s) atrás</option>)}</select></div>}>
      <p className="muted">Licitações com sinais de exclusividade/cota para ME e EPP no mesmo período de cada ano, comparadas ao ano anterior.</p>
      <Notice error={error} />
      {loading && !data ? <p className="empty">Carregando histórico…</p> : (
        <div className="years" style={{ opacity: loading ? 0.5 : 1 }}>
          {rows.map((row) => (
            <div key={row.ano} className="year">
              <div className="year-bar"><i style={{ height: `${(row[metric] / max) * 100}%` }} title={`${row.ano}`} /></div>
              <strong>{metric === 'valor_mpe' ? brlCompact(row[metric]) : num(row[metric])}</strong>
              <span>{row.ano}</span>
              <small className={row[variation] == null ? '' : row[variation] >= 0 ? 'up' : 'down'}>{pct(row[variation])}</small>
              <small>{num(row.quantidade_total)} licitações no total</small>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function Public() {
  const [filters, setFilters] = useState(defaultFilters());
  const [showOpen, setShowOpen] = useState(false);
  const [mapCity, setMapCity] = useState(null);
  const range = toRange(filters);
  const params = { municipio: filters.municipio, ...range };
  const summary = useFetch('/api/publico/resumo', params);
  const open = useFetch('/api/publico/abertos', { municipio: filters.municipio });
  const s = summary.data;
  const { data: cities } = useFetch('/api/geografia/municipios', {});
  const cityName = cities?.find((city) => String(city.id) === filters.municipio)?.nome;
  const pickCity = (name) => { const found = cities?.find((city) => city.nome === name); if (found) setFilters({ ...filters, municipio: String(found.id) }); };
  const scope = cityName || 'Ceará';

  return (
    <div className="page">
      <header className="page-head"><p className="eyebrow">VISÃO PÚBLICA · CEARÁ</p><h1>Licitações no {cityName ? cityName : 'Estado do Ceará'}</h1><p className="muted">Dados do PNCP atualizados em tempo real, restritos aos municípios cearenses.</p></header>
      <Card title="Filtros globais"><Filters filters={filters} onChange={setFilters} /></Card>
      <Notice error={summary.error} partial={s?.amostra_limitada} />
      {s && !s.consulta_completa && <div className="notice">Parte das consultas ao PNCP falhou; os números podem estar incompletos.</div>}
      <div className="stats">
        <Stat label={`Valor total estimado — ${scope}`} value={s ? brlCompact(s.valor_total) : ''} hint={s ? brl(s.valor_total) : ''} loading={summary.loading} tone="accent" />
        <Stat label="Licitações no período" value={s ? num(s.quantidade_total) : ''} hint={`${range.inicio} a ${range.fim} · 2 cliques: ver abertas`} loading={summary.loading} onOpen={() => setShowOpen(true)} />
        <Stat label={cityName ? `Licitações em ${cityName}` : 'Municípios com licitações'} value={s ? (cityName ? num(s.quantidade_total) : num(s.por_municipio.length)) : ''} loading={summary.loading} />
        <Stat label="Editais abertos para propostas" value={open.data ? num(open.data.total) : ''} loading={open.loading} tone="good" />
        <Stat label="Valor médio por licitação" value={s ? brlCompact(s.valor_medio) : ''} loading={summary.loading} />
        <Stat label="Com sinal ME/EPP" value={s ? num(s.quantidade_mpe) : ''} hint="identificados por texto do edital" loading={summary.loading} />
      </div>
      <CearaMap summary={s} selected={mapCity?.code} onSelect={(code, name) => setMapCity({ code, name })} />
      {mapCity && <MunicipalityPanel key={mapCity.code} code={mapCity.code} name={mapCity.name} onClose={() => setMapCity(null)} />}
      {showOpen && <OpenNoticesDialog municipio={filters.municipio} scope={scope} onClose={() => setShowOpen(false)} />}
      <div className="grid-2">
        <Card title="Evolução mensal">{s ? <ColumnChart rows={s.por_mes} labelKey="mes" title="Publicações por mês" /> : <p className="empty">{summary.loading ? 'Carregando…' : 'Sem dados.'}</p>}</Card>
        <Card title="Modalidades">{s ? <BarList rows={s.por_modalidade} labelKey="modalidade" /> : <p className="empty">Carregando…</p>}</Card>
      </div>
      <div className="grid-2">
        <Card title="Distribuição regional no Ceará" aside={<span className="muted">clique para filtrar</span>}>{s ? <BarList rows={s.por_municipio} labelKey="municipio" limit={10} onSelect={pickCity} selected={cityName} /> : <p className="empty">Carregando…</p>}</Card>
        <Card title="Resumo por município">{s ? <CityTable rows={[...s.por_municipio]} /> : <p className="empty">Carregando…</p>}</Card>
      </div>
      <MpeComparison params={params} />
      <Card title={`Editais abertos — ${scope}`} aside={<span className="muted">{open.data ? `${num(open.data.total)} no total` : ''}</span>}>
        <Notice error={open.error} />
        <div className="notice-grid">{(open.data?.editais || []).map((item) => <NoticeCard key={item.id} item={item} showStatus={false} />)}</div>
        {open.data && !open.data.editais.length && <p className="empty">Nenhum edital aberto para este filtro.</p>}
      </Card>
    </div>
  );
}
