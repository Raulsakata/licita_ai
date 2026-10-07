import { useState } from 'react';
import { brl, brlCompact, fmtDateTime, num, pct, useFetch } from '../lib/api';
import { BarList, Card, CityTable, ColumnChart, Filters, MpeMonthlyChart, Notice, NoticeCard, PriorityNotice, Stat, Tabs, defaultFilters, toRange } from '../components/ui';
import { CearaMap, MunicipalityPanel, OpenNoticesDialog } from '../components/map';

function MpeComparison({ initial }) {
  const [filters, setFilters] = useState(initial);
  const [metric, setMetric] = useState('quantidade_mpe');
  const [years, setYears] = useState('3');
  const { data, loading, error } = useFetch('/api/publico/comparativo-mpe', { municipio: filters.municipio, ...toRange(filters), anos: years });
  const rows = data?.anos || [];
  const value = (row) => (metric === 'participacao_mpe' ? (row.participacao_mpe ?? 0) : row[metric]);
  const max = Math.max(metric === 'participacao_mpe' ? 0.01 : 1, ...rows.map(value));
  const variation = (row, index) => {
    if (metric === 'participacao_mpe') return index && row.participacao_mpe != null && rows[index - 1].participacao_mpe != null ? `${((row.participacao_mpe - rows[index - 1].participacao_mpe) * 100).toFixed(1)} p.p.` : '—';
    return pct(row[metric === 'valor_mpe' ? 'variacao_valor_mpe' : 'variacao_quantidade_mpe']);
  };
  const display = (row) => (metric === 'valor_mpe' ? brlCompact(row.valor_mpe) : metric === 'participacao_mpe' ? (row.participacao_mpe == null ? '—' : `${(row.participacao_mpe * 100).toFixed(1)}%`) : num(row.quantidade_mpe));
  return (
    <Card title="Comparativo histórico — participação de Micro e Pequenas Empresas em editais fechados" className="mpe"
      aside={<div className="row-gap"><Tabs value={metric} onChange={setMetric} options={[['quantidade_mpe', 'Quantidade'], ['valor_mpe', 'Valor'], ['participacao_mpe', '% do total']]} /><select aria-label="Anos anteriores" value={years} onChange={(e) => setYears(e.target.value)}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} ano(s) atrás</option>)}</select></div>}>
      <Filters filters={filters} onChange={setFilters} />
      <p className="muted">Licitações já encerradas e liberadas para ME/EPP no mesmo período de cada ano, comparadas ao ano anterior.</p>
      <Notice error={error} partial={data?.anos?.some((row) => row.amostra_limitada)} incomplete={data?.anos?.some((row) => !row.consulta_completa)} />
      {loading && !data ? <p className="empty">Carregando histórico…</p> : (
        <div className="years" style={{ opacity: loading ? 0.5 : 1 }}>
          {rows.map((row, index) => (
            <div key={row.ano} className="year">
              <div className="year-bar"><i style={{ height: `${(value(row) / max) * 100}%` }} title={`${row.ano}`} /></div>
              <strong>{display(row)}</strong>
              <span>{row.ano}</span>
              <small>{variation(row, index)}</small>
              <small>{num(row.quantidade_mpe)} de {num(row.quantidade_encerradas)} encerradas</small>
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
  const [heroText, setHeroText] = useState('');
  const [mapCity, setMapCity] = useState(null);
  const [monthView, setMonthView] = useState('mpe');
  const mpeOnly = Boolean(filters.municipio);
  const range = toRange(filters);
  const params = { municipio: filters.municipio, ...range };
  const summary = useFetch('/api/publico/resumo', { ...params, somente_mpe: mpeOnly ? 1 : '' });
  const open = useFetch('/api/publico/abertos', { municipio: filters.municipio, somente_mpe: mpeOnly ? 1 : '' });
  const sync = useFetch('/api/publico/sincronizacao', {});
  const s = summary.data;
  const { data: cities } = useFetch('/api/geografia/municipios', {});
  const cityName = cities?.find((city) => String(city.id) === filters.municipio)?.nome;
  const pickCity = (name) => { const found = cities?.find((city) => city.nome === name); if (found) setFilters({ ...filters, municipio: String(found.id) }); };
  const scope = cityName || 'Ceará';
  const syncRunning = sync.data?.status === 'running' || sync.data?.open_status === 'running';
  const syncComplete = sync.data?.status === 'complete' && (!sync.data?.open_status || sync.data.open_status === 'complete');
  const syncLabel = syncRunning ? 'Sincronização em andamento'
    : syncComplete ? 'Última sincronização concluída'
      : sync.data?.status === 'error' || sync.data?.open_status === 'error' ? 'Falha na última tentativa'
        : sync.data ? 'Última tentativa parcial' : '';
  const syncTimestamp = syncRunning ? sync.data?.last_started_at
    : syncComplete ? sync.data?.last_completed_at
      : sync.data?.updated_at;

  return (
    <>
    <section className="hero">
      <h1>Portal de licitações do Ceará</h1>
      <form className="hero-search" role="search" onSubmit={(e) => { e.preventDefault(); setShowOpen(true); }}>
        <input type="search" aria-label="Buscar licitações abertas" placeholder="O que você procura? (objeto, órgão ou município)" value={heroText} onChange={(e) => setHeroText(e.target.value)} />
        <button type="submit" aria-label="Buscar">🔍</button>
      </form>
      {syncLabel && <small aria-live="polite">{syncLabel}{syncTimestamp && ` · ${fmtDateTime(syncTimestamp)}`} · atualização a cada 12 horas</small>}
    </section>
    <div className="profiles">
      <a className="profile" href="#"><h3>Cidadão</h3><p>Painel público com licitações, valores e mapa do Ceará.</p></a>
      <a className="profile" href="#/oportunidades"><h3>Empresa</h3><p>Para empresas (CNPJ): oportunidades compatíveis com seu CNAE.</p></a>
      <a className="profile" href="#/administrador"><h3>Administrador</h3><p>Gestão de empresas, fluxo de licitações e registros.</p></a>
    </div>
    <h2 className="section-title">Painel</h2>
    <div className="page">
      <Card title="Filtros globais"><Filters filters={filters} onChange={setFilters} /></Card>
      {mpeOnly && <PriorityNotice />}
      <Notice error={summary.error} partial={s?.amostra_limitada} incomplete={s && !s.consulta_completa} />
      <div className="stats">
        <Stat label={`Valor total estimado — ${scope}${mpeOnly ? ' (ME/EPP)' : ''}`} value={s ? brlCompact(s.valor_total) : ''} hint={s ? brl(s.valor_total) : ''} loading={summary.loading} tone="accent" />
        <Stat label={mpeOnly ? 'Licitações ME/EPP no período' : 'Licitações no período'} value={s ? num(s.quantidade_total) : ''} hint={`${range.inicio} a ${range.fim} · 2 cliques: ver abertas`} loading={summary.loading} onOpen={() => setShowOpen(true)} />
        <Stat label={cityName ? `Licitações em ${cityName}` : 'Municípios com licitações'} value={s ? (cityName ? num(s.quantidade_total) : num(s.por_municipio.length)) : ''} loading={summary.loading} />
        <Stat label={mpeOnly ? 'Editais abertos para ME/EPP' : 'Editais abertos para propostas'} value={open.data ? num(open.data.total) : ''} loading={open.loading} tone="good" />
        <Stat label="Valor médio por licitação" value={s ? brlCompact(s.valor_medio) : ''} loading={summary.loading} />
        <Stat label="Com sinal ME/EPP" value={s ? num(s.quantidade_mpe) : ''} hint="identificados por texto do edital" loading={summary.loading} />
      </div>
      <CearaMap summary={s} selected={mapCity?.code} onSelect={(code, name) => setMapCity({ code, name })} />
      {mapCity && <MunicipalityPanel key={mapCity.code} code={mapCity.code} name={mapCity.name} onClose={() => setMapCity(null)} />}
      {showOpen && <OpenNoticesDialog initialText={heroText} municipio={filters.municipio} scope={scope} mpeOnly={mpeOnly} onClose={() => setShowOpen(false)} />}
      <div className="grid-2">
        <Card title="Evolução mensal" aside={<Tabs value={monthView} onChange={setMonthView} options={[['mpe', 'Participação MPE (encerradas)'], ['pub', 'Publicações']]} />}>
          {!s ? <p className="empty">{summary.loading ? 'Carregando…' : 'Sem dados.'}</p> : monthView === 'mpe' ? <MpeMonthlyChart rows={s.mpe_mensal} /> : <ColumnChart rows={s.por_mes} labelKey="mes" title="Publicações por mês" />}
        </Card>
        <Card title="Modalidades">{s ? <BarList rows={s.por_modalidade} labelKey="modalidade" /> : <p className="empty">Carregando…</p>}</Card>
      </div>
      <div className="grid-2">
        <Card title="Distribuição regional no Ceará" aside={<span className="muted">clique para filtrar</span>}>{s ? <BarList rows={s.por_municipio} labelKey="municipio" limit={10} onSelect={pickCity} selected={cityName} /> : <p className="empty">Carregando…</p>}</Card>
        <Card title="Resumo por município">{s ? <CityTable rows={[...s.por_municipio]} /> : <p className="empty">Carregando…</p>}</Card>
      </div>
      <MpeComparison initial={filters} />
      <Card title={`Editais abertos${mpeOnly ? ' para ME/EPP' : ''} — ${scope}`} aside={<span className="muted">{open.data ? `${num(open.data.total)} no total` : ''}</span>}>
        <Notice error={open.error} partial={open.data?.amostra_limitada} incomplete={open.data && !open.data.consulta_completa} />
        <div className="notice-grid">{(open.data?.editais || []).map((item) => <NoticeCard key={item.id} item={item} showStatus={false} />)}</div>
        {open.data && !open.data.editais.length && <p className="empty">Nenhum edital aberto para este filtro.</p>}
      </Card>
    </div>
    </>
  );
}
