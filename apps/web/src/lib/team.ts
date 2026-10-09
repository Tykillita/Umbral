import { config } from './config';
import type { ReviewStatus } from './api/types';
import type { DemoRole, DemoSession } from './session';

export type LabelType = 'topic' | 'pair' | 'claim';
export interface HumanLabel {
  id: string;
  snapshotId: string;
  sheetHash: string;
  type: LabelType;
  itemId: string;
  value: string;
  comment: string;
  role: DemoRole;
  sessionId: string;
  labeler: string;
  labelMethod: 'human';
  createdAt: string;
}
export interface TeamDecision {
  eventId: string;
  snapshotId: string;
  topicId: string;
  caseId: string;
  caseVersion: number;
  status: ReviewStatus;
  role: DemoRole;
  sessionId: string;
  labeler: string;
  title: string;
  comment: string;
  createdAt: string;
}
interface LocalTeam {
  version: 1;
  decisions: TeamDecision[];
  labels: HumanLabel[];
  published: string[];
}
const KEY = 'umbral.team.v1';
const CHANGED = 'umbral:team-changed';
export const LABEL_VALUES: Record<LabelType, readonly string[]> = {
  topic: [
    'economia',
    'logistica_canal',
    'turismo',
    'servicios_publicos',
    'eventos_naturales',
    'regulacion',
    'indeterminado',
    'no_se',
  ],
  pair: ['si', 'no', 'no_se'],
  claim: ['respaldada', 'no_respaldada', 'cita_incorrecta', 'no_se'],
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const validRole = (role: unknown): role is DemoRole =>
  ['editor', 'producer', 'reviewer', 'juror'].includes(String(role));
export function validLabel(value: unknown): value is HumanLabel {
  if (!value || typeof value !== 'object') return false;
  const label = value as HumanLabel;
  return (
    UUID.test(label.id) &&
    UUID.test(label.sessionId) &&
    validRole(label.role) &&
    label.labelMethod === 'human' &&
    typeof label.snapshotId === 'string' &&
    Boolean(label.snapshotId) &&
    /^[0-9a-f]{64}$/i.test(label.sheetHash) &&
    Boolean(LABEL_VALUES[label.type]?.includes(label.value)) &&
    typeof label.itemId === 'string' &&
    Boolean(label.itemId) &&
    typeof label.comment === 'string' &&
    label.comment.length <= 2000 &&
    typeof label.labeler === 'string' &&
    label.labeler.length <= 120 &&
    typeof label.createdAt === 'string' &&
    Number.isFinite(Date.parse(label.createdAt))
  );
}
function validDecision(value: unknown): value is TeamDecision {
  if (!value || typeof value !== 'object') return false;
  const decision = value as TeamDecision;
  return (
    UUID.test(decision.eventId) &&
    UUID.test(decision.sessionId) &&
    validRole(decision.role) &&
    ['nuevo', 'en_revision', 'requiere_evidencia', 'aprobado_como_borrador', 'descartado'].includes(
      decision.status,
    ) &&
    ['snapshotId', 'topicId', 'caseId', 'title', 'labeler', 'comment'].every(
      (key) => typeof decision[key as keyof TeamDecision] === 'string',
    ) &&
    Number.isInteger(decision.caseVersion) &&
    decision.caseVersion > 0 &&
    Number.isFinite(Date.parse(decision.createdAt))
  );
}
export function readTeam(): LocalTeam {
  const raw = localStorage.getItem(KEY);
  if (!raw) return { version: 1, decisions: [], labels: [], published: [] };
  let state: LocalTeam;
  try {
    state = JSON.parse(raw) as LocalTeam;
  } catch {
    throw new Error(
      'La copia local de la mesa no se puede leer. Conserva el almacenamiento antes de recuperar una copia.',
    );
  }
  if (
    state.version !== 1 ||
    !Array.isArray(state.decisions) ||
    !Array.isArray(state.labels) ||
    !Array.isArray(state.published) ||
    !state.decisions.every(validDecision) ||
    !state.labels.every(validLabel) ||
    !state.published.every((id) => typeof id === 'string')
  )
    throw new Error('La copia local de la mesa tiene un formato incompatible.');
  return state;
}
async function changeTeam(change: (state: LocalTeam) => void): Promise<void> {
  const run = () => {
    const state = readTeam();
    change(state);
    try {
      localStorage.setItem(KEY, JSON.stringify(state));
    } catch {
      throw new Error(
        'No se pudo guardar la copia local. Revisa el espacio y los permisos del navegador antes de continuar.',
      );
    }
    window.dispatchEvent(new Event(CHANGED));
  };
  if (navigator.locks?.request) await navigator.locks.request(KEY, run);
  else run();
}
export function subscribeTeam(listener: () => void): () => void {
  const storage = (event: StorageEvent) => {
    if (event.key === KEY) listener();
  };
  window.addEventListener(CHANGED, listener);
  window.addEventListener('storage', storage);
  return () => {
    window.removeEventListener(CHANGED, listener);
    window.removeEventListener('storage', storage);
  };
}
export function sharedConfiguration(): { url: string; key: string } | null {
  const url = config.supabase.url,
    key = config.supabase.anonKey;
  if (!url && !key) return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error('La dirección de la mesa compartida no es válida.');
  }
  const local =
    ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname) &&
    ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);
  if (
    !key ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash ||
    parsed.pathname !== '/' ||
    (parsed.protocol !== 'https:' && !(local && parsed.protocol === 'http:'))
  )
    throw new Error('La mesa requiere una dirección HTTPS y una clave pública de Supabase.');
  if (!key.startsWith('sb_publishable_')) {
    try {
      if (JSON.parse(atob(key.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/'))).role !== 'anon')
        throw new Error();
    } catch {
      throw new Error('La mesa solo admite una clave pública anon o publishable de Supabase.');
    }
  }
  return { url: parsed.origin, key };
}
async function request(table: string, query: string, body?: Record<string, unknown>): Promise<unknown> {
  const settings = sharedConfiguration();
  if (!settings)
    throw new Error('La mesa compartida no está configurada. El trabajo se conserva en este navegador.');
  const controller = new AbortController(),
    timeout = window.setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(`${settings.url}/rest/v1/${table}?${query}`, {
      method: body ? 'POST' : 'GET',
      credentials: 'omit',
      signal: controller.signal,
      headers: {
        apikey: settings.key,
        ...(settings.key.startsWith('sb_publishable_') ? {} : { Authorization: `Bearer ${settings.key}` }),
        'Content-Type': 'application/json',
        ...(body ? { Prefer: 'resolution=ignore-duplicates,return=representation' } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok)
      throw new Error(
        `No se pudo ${body ? 'compartir' : 'leer'} la mesa (HTTP ${response.status}). La copia local se conserva; puedes reintentar.`,
      );
    return await response.json();
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError')
      throw new Error('La mesa tardó demasiado en responder. La copia local se conserva; puedes reintentar.');
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}
const decisionRow = (d: TeamDecision) => ({
  event_id: d.eventId,
  workspace: 'umbral',
  snapshot_id: d.snapshotId,
  topic_id: d.topicId,
  case_id: d.caseId,
  case_version: d.caseVersion,
  status: d.status,
  role: d.role,
  session_id: d.sessionId,
  labeler: d.labeler,
  title: d.title,
  comment: d.comment,
});
const labelRow = (l: HumanLabel) => ({
  id: l.id,
  workspace: 'umbral',
  snapshot_id: l.snapshotId,
  sheet_hash: l.sheetHash,
  type: l.type,
  item_id: l.itemId,
  value: l.value,
  comment: l.comment,
  role: l.role,
  session_id: l.sessionId,
  labeler: l.labeler,
  label_method: l.labelMethod,
});
export async function storeDecision(decision: TeamDecision): Promise<void> {
  if (!validDecision(decision)) throw new Error('La decisión no tiene un formato válido.');
  await changeTeam((state) => {
    if (!state.decisions.some((d) => d.eventId === decision.eventId)) state.decisions.push(decision);
  });
}
export async function storeLabel(
  session: DemoSession,
  body: Pick<HumanLabel, 'snapshotId' | 'sheetHash' | 'type' | 'itemId' | 'value' | 'comment'>,
): Promise<HumanLabel> {
  const label: HumanLabel = {
    ...body,
    ...session,
    id: crypto.randomUUID(),
    labelMethod: 'human',
    createdAt: new Date().toISOString(),
  };
  if (!validLabel(label)) throw new Error('La etiqueta no tiene un formato válido.');
  await changeTeam((state) => {
    state.labels.push(label);
  });
  return label;
}
let syncing: Promise<{ count: number }> | null = null;
export async function retrySharing(): Promise<{ count: number }> {
  if (syncing) return syncing;
  syncing = (async () => {
    const state = readTeam();
    let count = 0;
    for (const entry of [
      ...state.decisions.map((d) => ({
        id: d.eventId,
        table: 'umbral_decisions',
        key: 'event_id',
        row: decisionRow(d),
      })),
      ...state.labels.map((l) => ({ id: l.id, table: 'umbral_labels', key: 'id', row: labelRow(l) })),
    ]) {
      if (state.published.includes(entry.id)) continue;
      const result = await request(entry.table, `on_conflict=${entry.key}`, entry.row);
      if (!Array.isArray(result))
        throw new Error('La mesa devolvió una respuesta inesperada; la entrada sigue pendiente.');
      const confirmation = result.length
        ? result
        : await request(entry.table, `${entry.key}=eq.${entry.id}&workspace=eq.umbral&select=*`);
      if (
        !Array.isArray(confirmation) ||
        !confirmation.some((row: Row) =>
          Object.entries(entry.row).every(([key, value]) => row[key] === value),
        )
      )
        throw new Error('La mesa no confirmó el contenido de la entrada. La copia local sigue pendiente.');
      await changeTeam((current) => {
        if (!current.published.includes(entry.id)) current.published.push(entry.id);
      });
      count += 1;
    }
    return { count };
  })();
  try {
    return await syncing;
  } finally {
    syncing = null;
  }
}
type Row = Record<string, unknown>;
export async function fetchDecisions(): Promise<TeamDecision[]> {
  const rows = await request(
    'umbral_decisions',
    'workspace=eq.umbral&select=*&order=created_at.desc&limit=1000',
  );
  if (!Array.isArray(rows)) throw new Error('La mesa devolvió un historial incompatible.');
  return rows
    .map((row: Row) => ({
      eventId: row.event_id,
      snapshotId: row.snapshot_id,
      topicId: row.topic_id,
      caseId: row.case_id,
      caseVersion: row.case_version,
      status: row.status,
      role: row.role,
      sessionId: row.session_id,
      labeler: row.labeler,
      title: row.title,
      comment: row.comment,
      createdAt: row.created_at,
    }))
    .filter(validDecision);
}
export async function fetchLabels(snapshotId: string, sheetHash: string): Promise<HumanLabel[]> {
  const rows = await request(
    'umbral_labels',
    `workspace=eq.umbral&snapshot_id=eq.${encodeURIComponent(snapshotId)}&sheet_hash=eq.${sheetHash}&select=*&order=created_at.desc&limit=5000`,
  );
  if (!Array.isArray(rows)) throw new Error('La mesa devolvió etiquetas incompatibles.');
  return rows
    .map((row: Row) => ({
      id: row.id,
      snapshotId: row.snapshot_id,
      sheetHash: row.sheet_hash,
      type: row.type,
      itemId: row.item_id,
      value: row.value,
      comment: row.comment,
      role: row.role,
      sessionId: row.session_id,
      labeler: row.labeler,
      labelMethod: row.label_method,
      createdAt: row.created_at,
    }))
    .filter(validLabel);
}
export function mergeById<T>(local: T[], remote: T[], key: (value: T) => string): T[] {
  const map = new Map(local.map((value) => [key(value), value]));
  remote.forEach((value) => map.set(key(value), value));
  return [...map.values()];
}
export function latestLabels(labels: HumanLabel[], sessionId?: string): Map<string, HumanLabel> {
  const map = new Map<string, HumanLabel>();
  for (const label of [...labels].sort(
    (a, b) => a.createdAt.localeCompare(b.createdAt),
  )) {
    if (!sessionId || label.sessionId === sessionId)
      map.set(`${label.snapshotId}:${label.sheetHash}:${label.type}:${label.itemId}`, label);
  }
  return map;
}

/** La exportación ciega solo incluye los juicios de la sesión que la descarga. */
export function labelsForSession(labels: HumanLabel[], sessionId: string | undefined): HumanLabel[] {
  return sessionId ? labels.filter((label) => label.sessionId === sessionId) : [];
}
