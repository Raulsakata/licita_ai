import { useState } from 'react';
import { brl, num } from '../lib/api';
import { Card } from '../components/ui';
import { STAGES, useFavorites } from '../lib/tools';

const DemoBadge = () => <span className="badge demo">Demonstração · dados fictícios</span>;

function Funnel() {
  const { favs, toggle, setStage } = useFavorites();
  const entries = Object.values(favs);
  return (
    <Card title="Favoritos e funil de propostas" aside={<span className="muted">salvo neste navegador</span>}>
      {!entries.length && <p className="empty">Marque editais com ☆ nas listas para acompanhá-los aqui.</p>}
      <div className="funnel">
        {STAGES.map((stage) => (
          <section key={stage} className="funnel-col">
            <h3>{stage} <small>({entries.filter((e) => e.stage === stage).length})</small></h3>
            {entries.filter((e) => e.stage === stage).map(({ item }) => (
              <article key={item.id} className="funnel-item">
                <b>{item.orgao}</b>
                <p>{(item.objeto || '').slice(0, 110)}</p>
                <small>{item.valor ? brl(item.valor) : 'Valor N/I'}</small>
                <div className="row-gap">
                  <select aria-label="Etapa" value={stage} onChange={(e) => setStage(item.id, e.target.value)}>{STAGES.map((s) => <option key={s}>{s}</option>)}</select>
                  <button type="button" className="chip danger" onClick={() => toggle(item)}>Remover</button>
                </div>
              </article>
            ))}
          </section>
        ))}
      </div>
    </Card>
  );
}

function Alerts() {
  const [saved, setSaved] = useState(false);
  return (
    <Card title="Alertas por e-mail e WhatsApp" aside={<DemoBadge />}>
      <p className="muted">Receba aviso quando surgir um edital compatível com o CNAE da empresa. O envio real exige serviço pago (e-mail/WhatsApp), por isso esta tela é apenas uma simulação.</p>
      <form className="filters" onSubmit={(e) => { e.preventDefault(); setSaved(true); }}>
        <label>E-mail<input type="email" placeholder="empresa@exemplo.com" /></label>
        <label>WhatsApp<input type="tel" placeholder="(85) 90000-0000" /></label>
        <label>Frequência<select><option>Imediata</option><option>Resumo diário</option></select></label>
        <button className="primary" type="submit">Ativar alertas</button>
      </form>
      {saved && <p className="notice ok">Simulação: alertas ativados (nenhuma mensagem será enviada).</p>}
      <ul className="mock-list"><li>📧 Novo edital de <b>Serviços de TI</b> em Fortaleza — R$ 320.000</li><li>💬 Prazo termina em 2 dias: <b>Material de escritório</b> — Sobral</li></ul>
    </Card>
  );
}

const PRICES = [
  { item: 'Papel A4 (resma 500 fls)', media: 24.9, min: 19.5, max: 31.2, desconto: 0.12 },
  { item: 'Computador desktop', media: 4180, min: 3500, max: 5300, desconto: 0.18 },
  { item: 'Merenda escolar (kg de arroz)', media: 5.4, min: 4.6, max: 6.8, desconto: 0.09 },
  { item: 'Serviço de limpeza (mensal)', media: 18400, min: 14200, max: 23900, desconto: 0.15 },
];

function PriceHistory() {
  return (
    <Card title="Histórico de preços por item" aside={<DemoBadge />}>
      <p className="muted">Mostraria o preço praticado por item e o desconto típico dos vencedores. Depende de coletar os itens de cada licitação (muitas requisições extras ao PNCP), por isso usa valores fictícios.</p>
      <div className="scroll"><table><thead><tr><th>Item</th><th>Preço médio</th><th>Mínimo</th><th>Máximo</th><th>Desconto típico</th></tr></thead>
        <tbody>{PRICES.map((p) => <tr key={p.item}><td>{p.item}</td><td>{brl(p.media)}</td><td>{brl(p.min)}</td><td>{brl(p.max)}</td><td>{(p.desconto * 100).toFixed(0)}%</td></tr>)}</tbody></table></div>
    </Card>
  );
}

const SUPPLIERS = [
  ['Construtora Exemplo Ltda', 'Fortaleza', 42, 12800000], ['Comercial Sertão ME', 'Sobral', 37, 2100000],
  ['Tech Cariri EPP', 'Juazeiro do Norte', 29, 4750000], ['Alimentos Litoral Ltda', 'Aracati', 24, 3300000],
];

function Suppliers() {
  return (
    <Card title="Ranking de fornecedores vencedores" aside={<DemoBadge />}>
      <p className="muted">Exigiria consultar contratos e resultados do PNCP em grande volume. Os nomes abaixo são fictícios.</p>
      <div className="scroll"><table><thead><tr><th>#</th><th>Fornecedor</th><th>Município</th><th>Contratos</th><th>Valor total</th></tr></thead>
        <tbody>{SUPPLIERS.map(([n, c, q, v], i) => <tr key={n}><td>{i + 1}</td><td>{n}</td><td>{c}</td><td>{num(q)}</td><td>{brl(v)}</td></tr>)}</tbody></table></div>
    </Card>
  );
}

export default function Tools() {
  return (
    <div className="page">
      <header className="page-head"><p className="eyebrow">FERRAMENTAS</p><h1>Ferramentas para empresas</h1><p className="muted">Funil e favoritos funcionam de verdade; o restante é demonstração visual.</p></header>
      <Funnel />
      <div className="grid-2"><Alerts /><PriceHistory /></div>
      <Suppliers />
    </div>
  );
}
