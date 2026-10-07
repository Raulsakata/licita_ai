create table if not exists licita_ai.media_images (
  key text primary key,
  kind text not null check (kind in ('cidade', 'turismo')),
  title text not null,
  credit text,
  source_url text,
  content_type text not null default 'image/jpeg',
  data_b64 text not null,
  updated_at timestamptz not null default now()
);
create index if not exists media_images_kind_idx on licita_ai.media_images (kind);

alter table licita_ai.media_images enable row level security;
revoke all on licita_ai.media_images from anon, authenticated;
grant all on licita_ai.media_images to service_role;
