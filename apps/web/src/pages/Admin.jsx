import { useState } from 'react';
import { api, fmtDateTime, maskCnpj, num, useFetch } from '../lib/api';
import { BarList, Card, ColumnChart, Filters, Notice, NoticeCard, Stat, Tabs, defaultFilters, toRange } from '../components/ui';
import { LoginForm } from '../components/LoginForm';

function Overview({ token, onAuthError }) {
  const { data, loading, error } = useFetch('/api/admin/painel', {}, { token, onAuthError });
  return (
    <>
      <Notice error={error} />
      <div className="stats">
        <Stat label="Empresas cadastradas" value={num(data?.empresas_total)} loading={loading} tone="accent" />
        <Stat label="Ativas" value={num(data?.empresas_ativas)} loading={loading} tone="good" />
        <Stat label="Aptas (ME/EPP)" value={num(data?.empresas_aptas)} loading={loading} tone="good" />
        <Stat label="Não aptas" value={num(data?.empresas_nao_aptas)} loading={loading} tone="bad" />
        <Stat label="Logins (24h)" value={num(data?.logins_24h)} loading={loading} />
        <Stat label="Alertas (24h)" value={num(data?.alertas_24h)} loading={loading} tone={data?.alertas_24h ? 'bad' : ''} />
        <Stat label="Licitações armazenadas (CE)" value={data?.oportunidades_armazenadas == null ? 'N/D' : num(data.oportunidades_armazenadas)} loading={loading} />
        <Stat label="Supabase" value={data?.supabase === 'configured' ? 'Conectado' : 'Pendente'} loading={loading} />
      </div>
    </>
  );
}

function Companies({ token, onAuthError }) {
  const [version, setVersion] = useState(0);
  const { data, loading, error } = useFetch('/api/admin/empresas', { v: version }, { token, onAuthError });
  const [search, setSearch] = useState('');
  const [form, setForm] = useState({ cnpj: '', senha: '', razao_social: '', porte: '' });
  const [message, setMessage] = useState({ type: '', text: '' });
  const act = async (fn, okText) => {
    setMessage({ type: '', text: '' });
    try { await fn(); setMessage({ type: 'ok', text: okText }); setVersion((v) => v + 1); } catch (e) { if (e.status === 401) onAuthError(); setMessage({ type: 'error', text: e.message }); }
  };
  const rows = (data || []).filter((row) => `${row.cnpj} ${row.razao_social || ''}`.toLowerCase().includes(search.toLowerCase()));
  const resetPassword = (row) => { const senha = window.prompt(`Nova senha para ${row.razao_social || row.cnpj} (mín. 8 caracteres):`); if (senha) act(() => api(`/api/admin/empresas/${row.cnpj}`, { token, method: 'PATCH', body: { senha } }), 'Senha redefinida.'); };
  const remove = (row) => { if (window.confirm(`Remover ${row.razao_social || row.cnpj} e seu histórico?`)) act(() => api(`/api/admin/empresas/${row.cnpj}`, { token, method: 'DELETE' }), 'Empresa removida.'); };
  return (
    <>
      <Card title="Cadastrar empresa">
        <form className="inline-form" onSubmit={(e) => { e.preventDefault(); act(async () => { await api('/api/admin/empresas', { token, method: 'POST', body: { cnpj: form.cnpj, senha: form.senha, razao_social: form.razao_social || null, porte: form.porte || null } }); setForm({ cnpj: '', senha: '', razao_social: '', porte: '' }); }, 'Empresa cadastrada.'); }}>
          <label>CNPJ<input required value={form.cnpj} onChange={(e) => setForm({ ...form, cnpj: maskCnpj(e.target.value) })} /></label>
          <label>Senha inicial<input required type="password" minLength={8} autoComplete="new-password" value={form.senha} onChange={(e) => setForm({ ...form, senha: e.target.value })} /></label>
          <label>Razão social (opcional)<input value={form.razao_social} onChange={(e) => setForm({ ...form, razao_social: e.target.value })} /></label>
          <label>Porte (opcional)<select value={form.porte} onChange={(e) => setForm({ ...form, porte: e.target.value })}><option value="">Automático (OpenCNPJ)</option><option>ME</option><option>EPP</option><option>Demais</option></select></label>
          <button className="primary">Cadastrar</button>
        </form>
        {message.text && <div className={`notice ${message.type === 'error' ? 'error' : 'ok'}`} role="status">{message.text}</div>}
      </Card>
      <Card title="Empresas cadastradas" aside={<input className="search" type="search" placeholder="Buscar…" value={search} onChange={(e) => setSearch(e.target.value)} />}>
        <Notice error={error} />
        <div className="scroll"><table>
          <thead><tr><th>CNPJ</th><th>Razão social</th><th>Porte</th><th>Situação</th><th>Elegibilidade</th><th>Último acesso</th><th>Ações</th></tr></thead>
          <tbody>{rows.map((row) => (
            <tr key={row.cnpj} className={row.ativo ? '' : 'muted-row'}>
              <td>{maskCnpj(row.cnpj)}</td><td>{row.razao_social || '—'}</td><td>{row.porte || '—'}</td><td>{row.situacao_cadastral || '—'}</td>
              <td><span className={`badge ${row.rotulo === 'Apta' ? 'good' : 'bad'}`}>{row.rotulo}</span></td><td>{fmtDateTime(row.last_login_at)}</td>
              <td className="actions">
                <button type="button" className="chip" onClick={() => act(() => api(`/api/admin/empresas/${row.cnpj}`, { token, method: 'PATCH', body: { ativo: !row.ativo } }), row.ativo ? 'Empresa desativada.' : 'Empresa ativada.')}>{row.ativo ? 'Desativar' : 'Ativar'}</button>
                <button type="button" className="chip" onClick={() => resetPassword(row)}>Senha</button>
                <button type="button" className="chip danger" onClick={() => remove(row)}>Remover</button>
              </td>
            </tr>))}
            {!rows.length && <tr><td colSpan="7" className="empty">{loading ? 'Carregando…' : 'Nenhuma empresa encontrada.'}</td></tr>}</tbody>
        </table></div>
      </Card>
    </>
  );
}

function Logs({ token, onAuthError }) {
  const [level, setLevel] = useState('');
  const [tick, setTick] = useState(0);
  const { data, loading, error } = useFetch('/api/admin/logs', { nivel: level, v: tick }, { token, onAuthError });
  return (
    <Card title="Logs do sistema" aside={<div className="row-gap"><Tabs value={level} onChange={setLevel} options={[['', 'Todos'], ['info', 'Info'], ['warning', 'Alertas'], ['error', 'Erros']]} /><button type="button" className="chip" onClick={() => setTick((t) => t + 1)}>Atualizar</button></div>}>
      <Notice error={error} />
      <div className="scroll"><table><thead><tr><th>Data</th><th>Nível</th><th>Evento</th><th>Ator</th><th>Detalhes</th></tr></thead>
        <tbody>{(data || []).map((log, i) => <tr key={`${log.created_at}-${i}`}><td>{fmtDateTime(log.created_at)}</td><td><span className={`badge ${log.level === 'info' ? '' : 'bad'}`}>{log.level}</span></td><td>{log.event}</td><td>{log.actor}</td><td><code>{JSON.stringify(log.detail)}</code></td></tr>)}
          {!data?.length && <tr><td colSpan="5" className="empty">{loading ? 'Carregando…' : 'Sem registros.'}</td></tr>}</tbody></table></div>
    </Card>
  );
}

function Flow({ token, onAuthError }) {
  const [filters, setFilters] = useState(defaultFilters());
  const { data, loading, error } = useFetch('/api/admin/fluxo', { municipio: filters.municipio, ...toRange(filters) }, { token, onAuthError });
  return (
    <>
      <Card title="Fluxo de licitações do Ceará"><Filters filters={filters} onChange={setFilters} /></Card>
      <Notice error={error} partial={data?.amostra_limitada} />
      <div className="stats">
        <Stat label="Licitações" value={num(data?.quantidade_total)} loading={loading} tone="accent" />
        <Stat label="Municípios ativos" value={num(data?.por_municipio.length)} loading={loading} />
        <Stat label="Com sinal ME/EPP" value={num(data?.quantidade_mpe)} loading={loading} />
      </div>
      <div className="grid-2">
        <Card title="Publicações por mês">{data ? <ColumnChart rows={data.por_mes} labelKey="mes" title="Publicações" /> : <p className="empty">Carregando…</p>}</Card>
        <Card title="Top municípios">{data ? <BarList rows={data.por_municipio} labelKey="municipio" /> : <p className="empty">Carregando…</p>}</Card>
      </div>
      <Card title="Publicações mais recentes"><div className="notice-grid">{(data?.recentes || []).map((item) => <NoticeCard key={item.id} item={item} showStatus={false} />)}</div></Card>
    </>
  );
}

export default function Admin({ session, setSession }) {
  const [tab, setTab] = useState('painel');
  if (!session) {
    return (
      <div className="page narrow">
        <LoginForm title="Acesso administrativo" subtitle="Área restrita à gestão da plataforma."
          fields={[{ name: 'usuario', label: 'Usuário', autoComplete: 'username' }, { name: 'senha', label: 'Senha', type: 'password', autoComplete: 'current-password' }]}
          onSubmit={async (values) => setSession(await api('/api/auth/admin/login', { method: 'POST', body: values }))} />
      </div>
    );
  }
  const common = { token: session.token, onAuthError: () => setSession(null) };
  return (
    <div className="page">
      <header className="page-head company-head"><div><p className="eyebrow">ADMINISTRADOR</p><h1>Gestão da plataforma</h1><p className="muted">Sessão: {session.usuario}</p></div><button type="button" className="chip" onClick={() => setSession(null)}>Sair</button></header>
      <Tabs value={tab} onChange={setTab} options={[['painel', 'Painel'], ['empresas', 'Empresas'], ['fluxo', 'Fluxo CE'], ['logs', 'Logs']]} />
      {tab === 'painel' && <Overview {...common} />}
      {tab === 'empresas' && <Companies {...common} />}
      {tab === 'fluxo' && <Flow {...common} />}
      {tab === 'logs' && <Logs {...common} />}
    </div>
  );
}
