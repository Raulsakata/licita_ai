import { useState } from 'react';
import { brl, brlCompact, fmtDateTime, num, pct, useFetch } from '../lib/api';
import { BarList, Card, CityTable, ColumnChart, Filters, MpeMonthlyChart, Notice, NoticeCard, PriorityNotice, Stat, Tabs, defaultFilters, toRange } from '../components/ui';
import HeroSlides from '../components/HeroSlides';
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

function pctValue(value) {
  if (value == null) return '—';
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function TceMunicipalityTable({ rows }) {
  if (!rows?.length) return <p className="empty">Ainda não há municípios sincronizados para este ano.</p>;
  return (
    <div className="table-wrap">
      <div className="scroll"><table><thead><tr>
        <th>Município do Favorecido</th>
        <th>Demais Empresas (R$)</th>
        <th>Microempresa (R$)</th>
        <th>Empresa de Pequeno Porte (R$)</th>
        <th>Valor Total (R$)</th>
        <th>% Micro e Pequena Empresa</th>
        <th>% Microempresa</th>
      </tr></thead>
        <tbody>{rows.map((row) => {
          const micro = Number(row.micro_amount || 0);
          const total = Number(row.total_amount || 0);
          return <tr key={`${row.municipality_ibge_code}-${row.year}`}>
            <td>{row.municipality_name}</td>
            <td>{brl(row.demais_amount)}</td>
            <td>{brl(row.micro_amount)}</td>
            <td>{brl(row.pequena_amount)}</td>
            <td>{brl(row.total_amount)}</td>
            <td>{pctValue(row.mpe_percent)}</td>
            <td>{total > 0 ? `${((micro / total) * 100).toFixed(1)}%` : '—'}</td>
          </tr>;
        })}
        </tbody></table></div>
    </div>
  );
}

function TceNatureTable({ report }) {
  const rows = report?.naturezas || [];
  if (!rows.length) return <p className="empty">Sem detalhamento por natureza para este município/ano.</p>;
  const total = rows.reduce((acc, row) => ({
    total: acc.total + Number(row.total_amount || 0),
    mpe: acc.mpe + Number(row.mpe_amount || 0),
  }), { total: 0, mpe: 0 });
  return (
    <div className="table-wrap">
      <div className="scroll"><table><thead><tr>
        <th>Natureza das Despesas</th>
        <th>Total das Compras (R$)</th>
        <th>Valor MPE (R$)</th>
        <th>(%) MPE/Total</th>
      </tr></thead>
        <tbody>
          {rows.map((row) => <tr key={row.nature_code}>
            <td>{row.nature_name}</td>
            <td>{brl(row.total_amount)}</td>
            <td>{brl(row.mpe_amount)}</td>
            <td>{pctValue(row.mpe_percent)}</td>
          </tr>)}
          <tr>
            <td><b>TOTAL GERAL</b></td>
            <td><b>{brl(total.total)}</b></td>
            <td><b>{brl(total.mpe)}</b></td>
            <td><b>{total.total > 0 ? `${((total.mpe / total.total) * 100).toFixed(1)}%` : '—'}</b></td>
          </tr>
        </tbody></table></div>
      <p className="muted">Fonte: {report?.fonte || 'Portal da Transparência dos Municípios, TCE.CE.GOV.BR'}</p>
    </div>
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
  const reportYear = filters.modo === 'ano' ? Number(filters.ano) : Number(range.fim.slice(0, 4));
  const params = { municipio: filters.municipio, ...range };
  const summary = useFetch('/api/publico/resumo', { ...params, somente_mpe: mpeOnly ? 1 : '' });
  const open = useFetch('/api/publico/abertos', { municipio: filters.municipio, somente_mpe: mpeOnly ? 1 : '' });
  const sync = useFetch('/api/publico/sincronizacao', {});
  const tce = useFetch('/api/publico/compras-municipais', { municipio: filters.municipio, ano: reportYear });
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
      <HeroSlides />
      <h1>Portal de licitações do Ceará</h1>
      <div className="hero-buttons">
        <a className="hero-btn" href="#painel" onClick={(e) => { e.preventDefault(); document.getElementById('painel')?.scrollIntoView({ behavior: 'smooth' }); }}><b>Cidadão</b><span>Painel público, mapa e valores</span></a>
        <a className="hero-btn" href="#/oportunidades"><b>Empresa</b><span>Oportunidades pelo seu CNAE</span></a>
      </div>
      {syncLabel && <small aria-live="polite">{syncLabel}{syncTimestamp && ` · ${fmtDateTime(syncTimestamp)}`} · atualização a cada 12 horas</small>}
    </section>
    <div className="search-band"><form className="hero-search" role="search" onSubmit={(e) => { e.preventDefault(); setShowOpen(true); }}>
        <input type="search" aria-label="Buscar licitações abertas" placeholder="O que você procura? (objeto, órgão ou município)" value={heroText} onChange={(e) => setHeroText(e.target.value)} />
        <button type="submit" aria-label="Buscar">🔍</button>
      </form></div>
    <h2 className="section-title" id="painel">Painel</h2>
    <div className="page">
      <Card title="Filtros globais"><Filters filters={filters} onChange={setFilters} /></Card>
      <Card title={`Compras municipais (TCE-CE) — ${reportYear}`} aside={<span className="muted">{filters.municipio ? scope : `${num(tce.data?.quantidade_municipios || 0)} município(s) sincronizado(s)`}</span>}>
        {tce.loading && !tce.data ? <p className="empty">Carregando dados do TCE…</p> : null}
        {tce.error ? <Notice error={tce.error} /> : null}
        {!tce.loading && tce.data?.status === 'pending' && <p className="notice">Sincronização em fila para este município/ano. Recarregue em instantes.</p>}
        {!tce.loading && !filters.municipio && tce.data?.status === 'ready' && <TceMunicipalityTable rows={tce.data?.municipios || []} />}
        {!tce.loading && filters.municipio && tce.data?.status === 'ready' && <TceNatureTable report={tce.data} />}
      </Card>
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
