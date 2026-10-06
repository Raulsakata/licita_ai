import { useEffect, useRef, useState } from 'react';

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:3000';

export async function api(path, { token, method = 'GET', body, signal } = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    method, signal,
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail) ? payload.detail.map((d) => d.msg).join('; ') : payload.detail;
    const error = new Error(detail || 'Falha na requisição.');
    error.status = response.status;
    throw error;
  }
  return payload;
}

export const query = (params) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => { if (value !== '' && value != null) search.set(key, value); });
  const text = search.toString();
  return text ? `?${text}` : '';
};

// Busca com cancelamento: filtros novos descartam respostas antigas.
export function useFetch(path, params, { token, enabled = true, onAuthError } = {}) {
  const [state, setState] = useState({ data: null, loading: enabled, error: '' });
  const key = enabled ? `${path}${query(params || {})}` : null;
  const authRef = useRef(onAuthError);
  authRef.current = onAuthError;
  useEffect(() => {
    if (!key) return undefined;
    const controller = new AbortController();
    setState((current) => ({ ...current, loading: true, error: '' }));
    api(key, { token, signal: controller.signal })
      .then((data) => setState({ data, loading: false, error: '' }))
      .catch((error) => {
        if (error.name === 'AbortError') return;
        if (error.status === 401) authRef.current?.();
        setState({ data: null, loading: false, error: error.message });
      });
    return () => controller.abort();
  }, [key, token]);
  return state;
}

export const brl = (value) => Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
export const brlCompact = (value) => Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', notation: 'compact', maximumFractionDigits: 1 });
export const num = (value) => Number(value || 0).toLocaleString('pt-BR');
export const pct = (value) => (value == null ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(0)}%`);
export const fmtDate = (value) => (value ? new Date(value).toLocaleDateString('pt-BR') : '—');
export const fmtDateTime = (value) => (value ? new Date(value).toLocaleString('pt-BR') : '—');
export const maskCnpj = (value) => value.replace(/\D/g, '').slice(0, 14)
  .replace(/^(\d{2})(\d)/, '$1.$2').replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
  .replace(/\.(\d{3})(\d)/, '.$1/$2').replace(/(\d{4})(\d)/, '$1-$2');
