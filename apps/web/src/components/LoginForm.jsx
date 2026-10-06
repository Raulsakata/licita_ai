import { useState } from 'react';

export function LoginForm({ title, subtitle, fields, onSubmit }) {
  const [values, setValues] = useState(() => Object.fromEntries(fields.map((f) => [f.name, ''])));
  const [state, setState] = useState({ loading: false, error: '' });
  async function submit(event) {
    event.preventDefault();
    setState({ loading: true, error: '' });
    try { await onSubmit(values); } catch (error) { setState({ loading: false, error: error.message }); return; }
    setState({ loading: false, error: '' });
  }
  return (
    <form className="login card" onSubmit={submit}>
      <h1>{title}</h1><p className="muted">{subtitle}</p>
      {fields.map((field) => (
        <label key={field.name}>{field.label}
          <input type={field.type || 'text'} required autoComplete={field.autoComplete} inputMode={field.inputMode} placeholder={field.placeholder}
            value={values[field.name]} onChange={(e) => setValues({ ...values, [field.name]: field.mask ? field.mask(e.target.value) : e.target.value })} />
        </label>
      ))}
      {state.error && <div className="notice error" role="alert">{state.error}</div>}
      <button className="primary" disabled={state.loading}>{state.loading ? 'Entrando…' : 'Entrar'}</button>
    </form>
  );
}
