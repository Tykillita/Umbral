-- Esquema opcional para compartir decisiones y etiquetas del prototipo Umbral.
-- Ejecútalo manualmente en un proyecto Supabase propio; este archivo no configura
-- ni despliega ningún servicio. Los roles de demo son identificadores de interfaz,
-- no autenticación segura de personas.

create table if not exists public.umbral_decisions (
  event_id uuid primary key,
  workspace text not null check (workspace = 'umbral'),
  snapshot_id text not null check (length(snapshot_id) between 1 and 80),
  topic_id text not null check (length(topic_id) between 1 and 120),
  case_id text not null check (length(case_id) between 1 and 120),
  case_version integer not null check (case_version > 0),
  status text not null check (status in ('nuevo', 'en_revision', 'requiere_evidencia', 'aprobado_como_borrador', 'descartado')),
  role text not null check (role in ('editor', 'producer', 'reviewer', 'juror')),
  session_id uuid not null,
  labeler text not null check (length(labeler) <= 120),
  title text not null check (length(title) <= 500),
  comment text not null default '' check (length(comment) <= 2000),
  created_at timestamptz not null default now()
);

create table if not exists public.umbral_labels (
  id uuid primary key,
  workspace text not null check (workspace = 'umbral'),
  snapshot_id text not null check (length(snapshot_id) between 1 and 80),
  sheet_hash text not null check (sheet_hash ~ '^[0-9a-f]{64}$'),
  type text not null check (type in ('topic', 'pair', 'claim')),
  item_id text not null check (length(item_id) between 1 and 160),
  value text not null check (
    (type = 'topic' and value in ('economia', 'logistica_canal', 'turismo', 'servicios_publicos', 'eventos_naturales', 'regulacion', 'indeterminado', 'no_se')) or
    (type = 'pair' and value in ('si', 'no', 'no_se')) or
    (type = 'claim' and value in ('respaldada', 'no_respaldada', 'cita_incorrecta', 'no_se'))
  ),
  comment text not null default '' check (length(comment) <= 2000),
  role text not null check (role in ('editor', 'producer', 'reviewer', 'juror')),
  session_id uuid not null,
  labeler text not null check (length(labeler) <= 120),
  label_method text not null check (label_method = 'human'),
  created_at timestamptz not null default now()
);

create index if not exists umbral_decisions_workspace_created_idx
  on public.umbral_decisions (workspace, created_at desc);
create index if not exists umbral_labels_snapshot_hash_created_idx
  on public.umbral_labels (workspace, snapshot_id, sheet_hash, created_at desc);

alter table public.umbral_decisions enable row level security;
alter table public.umbral_labels enable row level security;

drop policy if exists umbral_decisions_read on public.umbral_decisions;
create policy umbral_decisions_read on public.umbral_decisions
  for select to anon, authenticated using (workspace = 'umbral');
drop policy if exists umbral_decisions_insert on public.umbral_decisions;
create policy umbral_decisions_insert on public.umbral_decisions
  for insert to anon, authenticated with check (workspace = 'umbral');

drop policy if exists umbral_labels_read on public.umbral_labels;
create policy umbral_labels_read on public.umbral_labels
  for select to anon, authenticated using (workspace = 'umbral');
drop policy if exists umbral_labels_insert on public.umbral_labels;
create policy umbral_labels_insert on public.umbral_labels
  for insert to anon, authenticated with check (workspace = 'umbral');

revoke all on public.umbral_decisions from public, anon, authenticated;
revoke all on public.umbral_labels from public, anon, authenticated;

grant select on public.umbral_decisions to anon, authenticated;
grant insert (
  event_id, workspace, snapshot_id, topic_id, case_id, case_version, status,
  role, session_id, labeler, title, comment
) on public.umbral_decisions to anon, authenticated;

grant select on public.umbral_labels to anon, authenticated;
grant insert (
  id, workspace, snapshot_id, sheet_hash, type, item_id, value, comment,
  role, session_id, labeler, label_method
) on public.umbral_labels to anon, authenticated;
