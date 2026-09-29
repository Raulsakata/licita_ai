-- Tabela pública para recebimento de envios de formulário do site (somente inserção).
create table if not exists public.publica (
  id uuid primary key default gen_random_uuid(),
  payload jsonb not null,
  created_at timestamptz not null default now()
);

alter table public.publica enable row level security;

-- Apenas INSERT é permitido para anon/authenticated; sem policies de select/update/delete.
drop policy if exists "publica_insert_anon" on public.publica;
create policy "publica_insert_anon"
  on public.publica
  for insert
  to anon
  with check (true);

drop policy if exists "publica_insert_authenticated" on public.publica;
create policy "publica_insert_authenticated"
  on public.publica
  for insert
  to authenticated
  with check (true);
