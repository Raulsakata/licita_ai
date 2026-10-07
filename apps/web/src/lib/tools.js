import { useCallback, useEffect, useState } from 'react';

export const STAGES = ['Analisando', 'Proposta enviada', 'Ganhou', 'Perdeu'];
const FAV_KEY = 'licita.favoritos';
const THEME_KEY = 'licita.tema';

const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };

// Favoritos e funil ficam no navegador (sem custo e sem backend).
export function useFavorites() {
  const [favs, setFavs] = useState(() => read(FAV_KEY, {}));
  useEffect(() => {
    const sync = () => setFavs(read(FAV_KEY, {}));
    window.addEventListener('licita-favs', sync);
    window.addEventListener('storage', sync);
    return () => { window.removeEventListener('licita-favs', sync); window.removeEventListener('storage', sync); };
  }, []);
  const save = useCallback((next) => {
    localStorage.setItem(FAV_KEY, JSON.stringify(next));
    window.dispatchEvent(new Event('licita-favs'));
  }, []);
  const toggle = (item) => {
    const current = read(FAV_KEY, {});
    if (current[item.id]) delete current[item.id]; else current[item.id] = { item, stage: STAGES[0] };
    save(current);
  };
  const setStage = (id, stage) => { const current = read(FAV_KEY, {}); if (current[id]) { current[id].stage = stage; save(current); } };
  return { favs, toggle, setStage };
}

export function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_KEY) || 'light');
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem(THEME_KEY, theme); }, [theme]);
  return [theme, () => setTheme(theme === 'dark' ? 'light' : 'dark')];
}

export function daysLeft(value) {
  if (!value) return null;
  const diff = new Date(value).getTime() - Date.now();
  return diff <= 0 ? null : Math.ceil(diff / 86400000);
}

export function exportCsv(rows, name = 'licitacoes') {
  const cols = [['id', 'ID PNCP'], ['objeto', 'Objeto'], ['orgao', 'Órgão'], ['municipio', 'Município'], ['modalidade', 'Modalidade'], ['valor', 'Valor'], ['encerramento_propostas', 'Encerramento'], ['link_edital', 'Link']];
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const body = [cols.map(([, h]) => esc(h)).join(';'), ...rows.map((r) => cols.map(([k]) => esc(r[k])).join(';'))].join('\r\n');
  const url = URL.createObjectURL(new Blob([`\uFEFF${body}`], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url; a.download = `${name}.csv`; a.click();
  URL.revokeObjectURL(url);
}
