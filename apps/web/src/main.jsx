import { StrictMode, useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Public from './pages/Public';
import Company from './pages/Company';
import Admin from './pages/Admin';
import './app.css';

const ROUTES = { '': 'inicio', '#/oportunidades': 'empresa', '#/administrador': 'admin' };

// Sessão só dura a aba aberta; o token nunca vai para localStorage.
function useSession(key) {
  const [session, setSessionState] = useState(() => { try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; } });
  const setSession = useCallback((value) => {
    if (value) sessionStorage.setItem(key, JSON.stringify(value)); else sessionStorage.removeItem(key);
    setSessionState(value);
  }, [key]);
  return [session, setSession];
}

function App() {
  const [hash, setHash] = useState(window.location.hash);
  const [menuOpen, setMenuOpen] = useState(false);
  const [company, setCompany] = useSession('licita.empresa');
  const [admin, setAdmin] = useSession('licita.admin');
  useEffect(() => { const onHash = () => { setHash(window.location.hash); setMenuOpen(false); window.scrollTo(0, 0); }; window.addEventListener('hashchange', onHash); return () => window.removeEventListener('hashchange', onHash); }, []);
  const route = ROUTES[hash] || 'inicio';
  const links = [['#', 'inicio', 'Início público', '◈'], ['#/oportunidades', 'empresa', 'Oportunidades', '▣'], ['#/administrador', 'admin', 'Administrador', '⚙']];
  return (
    <div className="app-shell">
      <button type="button" className="menu-toggle" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>☰ Menu</button>
      <aside className={`sidebar ${menuOpen ? 'open' : ''}`}>
        <div className="brand"><span>◈</span><div><strong>Licita AI</strong><small>Licitações do Ceará</small></div></div>
        <nav aria-label="Principal">{links.map(([href, id, label, icon]) => <a key={id} href={href} className={route === id ? 'active' : ''} aria-current={route === id ? 'page' : undefined}><i>{icon}</i>{label}</a>)}</nav>
        <footer>Dados públicos<br />PNCP · IBGE · OpenCNPJ</footer>
      </aside>
      <main>
        {route === 'inicio' && <Public />}
        {route === 'empresa' && <Company session={company} setSession={setCompany} />}
        {route === 'admin' && <Admin session={admin} setSession={setAdmin} />}
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>);
