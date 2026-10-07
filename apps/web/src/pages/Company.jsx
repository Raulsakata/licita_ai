import { useMemo, useState } from 'react';
import { api, maskCnpj, num, useFetch } from '../lib/api';
import { Card, Filters, Notice, NoticeCard, Stat, defaultFilters, toRange } from '../components/ui';
import CompanyInsights from '../components/company_insights';
import { LoginForm } from '../components/LoginForm';

function Panel({ session, onLogout }) {
  const [filters, setFilters] = useState(defaultFilters());
  const [text, setText] = useState('');
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [showRestricted, setShowRestricted] = useState(false);
  const range = toRange(filters);
  const { data, loading, error } = useFetch('/api/empresa/oportunidades', { municipio: filters.municipio, ...range }, { token: session.token, onAuthError: onLogout });
  const company = data?.empresa || session.empresa;
  const apt = company.apta_indicativamente;

  const visible = useMemo(() => (data?.aptas || []).filter((item) => {
    if (onlyOpen && !(item.encerramento_propostas && new Date(item.encerramento_propostas) > new Date())) return false;
    const haystack = `${item.objeto} ${item.orgao} ${item.municipio}`.toLowerCase();
    return haystack.includes(text.toLowerCase());
  }), [data, text, onlyOpen]);

  return (
    <div className="page">
      <header className="page-head company-head">
        <div><p className="eyebrow">PERFIL EMPRESA</p><h1>{company.razao_social || company.cnpj}</h1>
          <p className="muted">CNPJ {maskCnpj(company.cnpj)} · Porte: {company.porte || 'N/I'} · Natureza jurídica: {company.natureza_juridica || 'N/I'}</p></div>
        <div className="row-gap"><span className={`status-pill ${apt ? 'good' : 'bad'}`}>{apt ? '✔ Apta' : '✖ Não Apta'}</span><button type="button" className="chip" onClick={onLogout}>Sair</button></div>
      </header>
      {!apt && <div className="notice restricted-banner" role="status"><b>Não Apta para editais com exigência de porte.</b> {company.motivo} Editais exclusivos para ME/EPP ficam bloqueados; você continua vendo os demais.</div>}
      <Card title="Refinar busca"><Filters filters={filters} onChange={setFilters} /></Card>
      <Notice error={error} partial={data?.amostra_limitada} incomplete={data && !data.consulta_completa} />
      {data && !data.cnae_disponivel && <div className="notice error" role="alert">Não foi possível obter o CNAE da sua empresa. Sem ele não há como indicar licitações compatíveis; entre em contato com o administrador.</div>}
      {data?.cnae?.length > 0 && <div className="notice ok"><b>Filtro por CNAE:</b> exibindo apenas licitações cujo objeto cita termos de: {data.cnae.map((c) => c.descricao).join(' · ')}.</div>}
      <div className="stats">
        <Stat label="Licitações compatíveis em que você pode participar" value={data ? num(data.aptas.length) : ''} loading={loading} tone="good" />
        <Stat label="Bloqueadas por porte" value={data ? num(data.total_nao_aptas) : ''} loading={loading} tone={data?.total_nao_aptas ? 'bad' : ''} />
        <Stat label="Fora do seu CNAE (ocultas)" value={data ? num(data.total_incompativeis) : ''} loading={loading} />
      </div>
      <CompanyInsights items={data?.aptas || []} />
      <Card title="Oportunidades aptas" aside={<div className="row-gap"><label className="check"><input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Somente com propostas abertas</label></div>}>
        <input className="search" type="search" placeholder="Buscar por objeto, órgão ou município…" value={text} onChange={(e) => setText(e.target.value)} />
        <p className="muted" aria-live="polite">{loading ? 'Atualizando…' : `${num(visible.length)} licitação(ões) exibida(s)`}</p>
        <div className="notice-grid" style={{ opacity: loading ? 0.5 : 1 }}>{visible.map((item) => <NoticeCard key={item.id} item={item} />)}</div>
        {data && !visible.length && !loading && <p className="empty">Nenhuma licitação compatível com o seu CNAE para os filtros atuais.</p>}
      </Card>
      {data?.total_nao_aptas > 0 && (
        <Card title="Editais com restrição de porte" aside={<button type="button" className="chip" onClick={() => setShowRestricted(!showRestricted)}>{showRestricted ? 'Ocultar' : `Mostrar (${data.total_nao_aptas})`}</button>}>
          {showRestricted && <div className="notice-grid">{data.nao_aptas.map((item) => <NoticeCard key={item.id} item={item} locked />)}</div>}
        </Card>
      )}
    </div>
  );
}

export default function Company({ session, setSession }) {
  if (!session) {
    return (
      <div className="page narrow">
        <LoginForm title="Oportunidades para Empresas" subtitle="Entre com o CNPJ e a senha cadastrados."
          fields={[{ name: 'cnpj', label: 'CNPJ', mask: maskCnpj, inputMode: 'numeric', placeholder: '00.000.000/0000-00', autoComplete: 'username' }, { name: 'senha', label: 'Senha', type: 'password', autoComplete: 'current-password' }]}
          onSubmit={async (values) => setSession(await api('/api/auth/empresa/login', { method: 'POST', body: { cnpj: values.cnpj, senha: values.senha } }))} />
      </div>
    );
  }
  return <Panel session={session} onLogout={() => setSession(null)} />;
}
