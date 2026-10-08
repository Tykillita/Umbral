import { ANSWER_LABEL } from '../labels';
import type { QueryContext, QueryResponse } from './types';

export type AssistantTurn = {
  id: string;
  question: string;
  topicId: string | null;
  topicTitle?: string;
  /** Contexto estructurado de la respuesta anterior que se envió con esta pregunta (si la conversación continuaba). */
  followUp?: QueryContext | null;
  createdAt: string;
  state: 'pending' | 'interrupted' | 'error' | 'complete';
  error?: string;
  retryAfter?: number | null;
  retryAvailableAt?: string | null;
  result?: QueryResponse;
  relatedTitles?: Record<string, string>;
  /** Respuesta recibida mientras la persona no estaba mirando esa conversación; se limpia al verla. */
  unread?: boolean;
  /** `modelo` cuando `result.answer` fue redactada con IA y validada por código; `reglas` (o ausente) si es la respuesta determinista. */
  answerMode?: 'reglas' | 'modelo';
  /** Texto de la respuesta por reglas, conservado cuando se redactó con IA. */
  rulesAnswer?: string;
  composedBy?: string;
  /** Por qué no se redactó con IA (cuota, límite, validación…); la respuesta por reglas se conserva. */
  composeNote?: string;
};

/** Versión del formato guardado en IndexedDB. Súbela cuando cambie la forma de `AssistantConversation`. */
export const ASSISTANT_SCHEMA_VERSION = 1;
export const MAX_ASSISTANT_CONVERSATIONS = 50;
const TOMBSTONE_TTL_MS = 30 * 24 * 60 * 60 * 1000;

export type AssistantConversation = {
  id: string;
  namespace: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  draft: string;
  scopeTopicId: string | null;
  scopeTopicTitle: string;
  turns: AssistantTurn[];
  scrollAnchor?: { turnId: string; offset: number } | null;
  schemaVersion?: number;
};

export type AssistantHistorySnapshot = {
  conversations: AssistantConversation[];
  lastConversationId: string | null;
  persistent: boolean;
};

const DB_NAME = 'umbral-assistant-history-v1';
const DB_VERSION = 1;
const CONVERSATIONS = 'conversations';
const SETTINGS = 'settings';
const TOMBSTONES = 'tombstones';
const memory = new Map<string, AssistantConversation>();
const memoryTombstones = new Set<string>();
const lastByNamespace = new Map<string, string>();
const channels = new Map<string, { channel: BroadcastChannel; listeners: number }>();
let database: Promise<IDBDatabase> | null = null;

function key(namespace: string, id: string) { return `${namespace}\u0000${id}`; }

/** Mensaje entre pestañas: `saved`/`deleted` llevan el id para recargar solo esa conversación; `changed` fuerza una recarga completa. */
export type AssistantChange = { type: 'saved' | 'deleted' | 'changed'; id?: string };

function emit(namespace: string, change: AssistantChange) {
  if (typeof BroadcastChannel === 'undefined') return;
  const open = channels.get(namespace);
  if (open) { open.channel.postMessage(change); return; }
  const transient = new BroadcastChannel(`${DB_NAME}:${namespace}`);
  transient.postMessage(change);
  transient.close();
}

export function subscribeAssistantHistory(namespace: string, listener: (change: AssistantChange) => void): () => void {
  if (typeof BroadcastChannel === 'undefined') return () => {};
  let entry = channels.get(namespace);
  if (!entry) {
    entry = { channel: new BroadcastChannel(`${DB_NAME}:${namespace}`), listeners: 0 };
    channels.set(namespace, entry);
  }
  const current = entry;
  const handler = (event: MessageEvent) => {
    const data = event.data as Partial<AssistantChange> | null;
    listener(data && (data.type === 'saved' || data.type === 'deleted') && typeof data.id === 'string' ? { type: data.type, id: data.id } : { type: 'changed' });
  };
  current.listeners += 1;
  current.channel.addEventListener('message', handler);
  return () => {
    current.channel.removeEventListener('message', handler);
    current.listeners -= 1;
    if (current.listeners <= 0) {
      current.channel.close();
      if (channels.get(namespace) === current) channels.delete(namespace);
    }
  };
}

function openDatabase(): Promise<IDBDatabase> {
  if (database) return database;
  database = new Promise<IDBDatabase>((resolve, reject) => {
    if (typeof indexedDB === 'undefined') { reject(new Error('IndexedDB no disponible')); return; }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      const conversations = db.objectStoreNames.contains(CONVERSATIONS)
        ? request.transaction!.objectStore(CONVERSATIONS)
        : db.createObjectStore(CONVERSATIONS, { keyPath: 'key' });
      if (!conversations.indexNames.contains('namespace')) conversations.createIndex('namespace', 'namespace');
      if (!conversations.indexNames.contains('updatedAt')) conversations.createIndex('updatedAt', 'updatedAt');
      if (!db.objectStoreNames.contains(SETTINGS)) db.createObjectStore(SETTINGS, { keyPath: 'namespace' });
      if (!db.objectStoreNames.contains(TOMBSTONES)) db.createObjectStore(TOMBSTONES, { keyPath: 'key' });
    };
    request.onsuccess = () => {
      request.result.onversionchange = () => { request.result.close(); database = null; };
      resolve(request.result);
      void purgeOldTombstones(request.result);
    };
    request.onerror = () => reject(request.error ?? new Error('No se pudo abrir el historial local'));
    request.onblocked = () => reject(new Error('El historial está ocupado en otra pestaña'));
  }).catch((error) => {
    database = null;
    throw error;
  });
  return database!;
}

const ANSWER_STATUSES = new Set(['respondida', 'parcial', 'contradiccion', 'abstencion']);
const TURN_STATES = new Set(['pending', 'interrupted', 'error', 'complete']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function validResult(value: unknown): value is QueryResponse {
  if (!isRecord(value)) return false;
  return typeof value.answer === 'string' && typeof value.queryId === 'string' && typeof value.snapshotId === 'string'
    && typeof value.rulesVersion === 'string' && typeof value.answerStatus === 'string' && ANSWER_STATUSES.has(value.answerStatus)
    && ['citations', 'hits', 'missing', 'contradictions', 'warnings', 'relatedTopicIds'].every((field) => Array.isArray(value[field]))
    && isRecord(value.retrieval) && typeof value.retrieval.coverage === 'number';
}

/** Valida un registro leído del disco; descarta lo irreparable y degrada resultados malformados a un error reintentable. */
export function normalizeAssistantConversation(raw: unknown): AssistantConversation | null {
  if (!isRecord(raw) || typeof raw.id !== 'string' || typeof raw.namespace !== 'string' || typeof raw.updatedAt !== 'string' || !Array.isArray(raw.turns)) return null;
  const version = typeof raw.schemaVersion === 'number' ? raw.schemaVersion : 0;
  if (version > ASSISTANT_SCHEMA_VERSION) return null;
  const turns: AssistantTurn[] = [];
  for (const entry of raw.turns) {
    if (!isRecord(entry) || typeof entry.id !== 'string' || typeof entry.question !== 'string' || typeof entry.state !== 'string' || !TURN_STATES.has(entry.state)) continue;
    const turn = entry as unknown as AssistantTurn;
    if (turn.state === 'complete' && !validResult(turn.result)) {
      turns.push({ ...turn, state: 'error', result: undefined, error: 'La respuesta guardada no se pudo leer. Reintenta la consulta.', retryAfter: null, retryAvailableAt: null });
    } else turns.push(turn);
  }
  return {
    id: raw.id, namespace: raw.namespace, updatedAt: raw.updatedAt,
    title: typeof raw.title === 'string' && raw.title ? raw.title : 'Nueva conversación',
    createdAt: typeof raw.createdAt === 'string' ? raw.createdAt : raw.updatedAt,
    draft: typeof raw.draft === 'string' ? raw.draft : '',
    scopeTopicId: typeof raw.scopeTopicId === 'string' ? raw.scopeTopicId : null,
    scopeTopicTitle: typeof raw.scopeTopicTitle === 'string' ? raw.scopeTopicTitle : '',
    turns,
    scrollAnchor: isRecord(raw.scrollAnchor) && typeof raw.scrollAnchor.turnId === 'string' && typeof raw.scrollAnchor.offset === 'number'
      ? { turnId: raw.scrollAnchor.turnId, offset: raw.scrollAnchor.offset } : null,
    schemaVersion: ASSISTANT_SCHEMA_VERSION,
  };
}

async function purgeOldTombstones(db: IDBDatabase): Promise<void> {
  try {
    const tx = db.transaction(TOMBSTONES, 'readwrite');
    const store = tx.objectStore(TOMBSTONES);
    const cutoff = Date.now() - TOMBSTONE_TTL_MS;
    const cursorRequest = store.openCursor();
    cursorRequest.onsuccess = () => {
      const cursor = cursorRequest.result;
      if (!cursor) return;
      const deletedAt = Date.parse((cursor.value as { deletedAt?: string }).deletedAt ?? '');
      if (Number.isFinite(deletedAt) && deletedAt < cutoff) cursor.delete();
      cursor.continue();
    };
  } catch { /* La purga es mantenimiento opcional. */ }
}

async function pruneConversations(namespace: string, keep: string): Promise<void> {
  try {
    const db = await openDatabase();
    const tx = db.transaction(CONVERSATIONS, 'readwrite');
    const store = tx.objectStore(CONVERSATIONS);
    const items = await requestValue(store.index('namespace').getAll(namespace) as IDBRequest<Array<AssistantConversation & { key: string }>>);
    if (items.length <= MAX_ASSISTANT_CONVERSATIONS) return;
    const oldest = items.filter((item) => item.key !== keep).sort((a, b) => a.updatedAt.localeCompare(b.updatedAt)).slice(0, items.length - MAX_ASSISTANT_CONVERSATIONS);
    for (const item of oldest) { store.delete(item.key); memory.delete(item.key); }
  } catch { /* Sin poda, el historial sigue siendo válido. */ }
}

function requestValue<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Falló una operación del historial'));
  });
}

export async function loadAssistantHistory(namespace: string): Promise<AssistantHistorySnapshot> {
  try {
    const db = await openDatabase();
    const tx = db.transaction([CONVERSATIONS, SETTINGS], 'readonly');
    const [items, settings] = await Promise.all([
      requestValue(tx.objectStore(CONVERSATIONS).index('namespace').getAll(namespace) as IDBRequest<Array<AssistantConversation & { key: string }>>),
      requestValue(tx.objectStore(SETTINGS).get(namespace) as IDBRequest<{ namespace: string; lastConversationId?: string }>),
    ]);
    const conversations = items
      .map(({ key: _key, ...item }) => normalizeAssistantConversation(item))
      .filter((item): item is AssistantConversation => item !== null)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    for (const item of conversations) memory.set(key(namespace, item.id), item);
    const lastConversationId = settings?.lastConversationId ?? lastByNamespace.get(namespace) ?? null;
    if (lastConversationId) lastByNamespace.set(namespace, lastConversationId);
    return { conversations, lastConversationId, persistent: true };
  } catch {
    return {
      conversations: [...memory.values()].filter((item) => item.namespace === namespace && !memoryTombstones.has(key(item.namespace, item.id))).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
      lastConversationId: lastByNamespace.get(namespace) ?? null,
      persistent: false,
    };
  }
}

/** Lee una sola conversación (recarga selectiva tras un aviso de otra pestaña). `null` si no existe o fue eliminada. */
export async function loadAssistantConversation(namespace: string, id: string): Promise<AssistantConversation | null> {
  const memoryKey = key(namespace, id);
  if (memoryTombstones.has(memoryKey)) return null;
  try {
    const db = await openDatabase();
    const tx = db.transaction(CONVERSATIONS, 'readonly');
    const raw = await requestValue(tx.objectStore(CONVERSATIONS).get(memoryKey) as IDBRequest<(AssistantConversation & { key: string }) | undefined>);
    if (!raw) return null;
    const { key: _key, ...rest } = raw;
    const item = normalizeAssistantConversation(rest);
    if (item) memory.set(memoryKey, item);
    return item;
  } catch {
    return memory.get(memoryKey) ?? null;
  }
}

export async function saveAssistantConversation(conversation: AssistantConversation): Promise<boolean> {
  const item = { ...conversation, schemaVersion: ASSISTANT_SCHEMA_VERSION, key: key(conversation.namespace, conversation.id) };
  if (memoryTombstones.has(item.key)) return false;
  memory.set(item.key, conversation);
  try {
    const db = await openDatabase();
    const tx = db.transaction([CONVERSATIONS, TOMBSTONES], 'readwrite');
    let stored = false;
    const tombstone = tx.objectStore(TOMBSTONES).get(item.key);
    tombstone.onsuccess = () => {
      if (tombstone.result) return;
      tx.objectStore(CONVERSATIONS).put(item);
      stored = true;
    };
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error('No se pudo guardar la conversación'));
      tx.onabort = () => reject(tx.error ?? new Error('Se canceló el guardado de la conversación'));
    });
    if (!stored) memory.delete(item.key);
    else void pruneConversations(conversation.namespace, item.key);
    emit(conversation.namespace, stored ? { type: 'saved', id: conversation.id } : { type: 'changed' });
    return stored;
  } catch {
    return false;
  }
}

export async function setLastAssistantConversation(namespace: string, id: string | null): Promise<boolean> {
  if (id) lastByNamespace.set(namespace, id); else lastByNamespace.delete(namespace);
  try {
    const db = await openDatabase();
    const tx = db.transaction(SETTINGS, 'readwrite');
    if (id) tx.objectStore(SETTINGS).put({ namespace, lastConversationId: id });
    else tx.objectStore(SETTINGS).delete(namespace);
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error('No se pudo guardar la conversación activa'));
      tx.onabort = () => reject(tx.error ?? new Error('Se canceló el guardado de la conversación activa'));
    });
    return true;
  } catch { return false; }
}

export async function deleteAssistantConversation(namespace: string, id: string): Promise<boolean> {
  const deletedKey = key(namespace, id);
  memoryTombstones.add(deletedKey);
  memory.delete(deletedKey);
  try {
    const db = await openDatabase();
    const tx = db.transaction([CONVERSATIONS, TOMBSTONES, SETTINGS], 'readwrite');
    tx.objectStore(CONVERSATIONS).delete(key(namespace, id));
    tx.objectStore(TOMBSTONES).put({ key: key(namespace, id), namespace, id, deletedAt: new Date().toISOString() });
    const settings = tx.objectStore(SETTINGS).get(namespace);
    settings.onsuccess = () => {
      if (settings.result?.lastConversationId === id) tx.objectStore(SETTINGS).delete(namespace);
    };
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error('No se pudo eliminar la conversación'));
      tx.onabort = () => reject(tx.error ?? new Error('Se canceló la eliminación'));
    });
    emit(namespace, { type: 'deleted', id });
    return true;
  } catch { return false; }
}

export function newAssistantId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function assistantTitle(question: string): string {
  const normalized = question.replace(/\s+/g, ' ').trim();
  return normalized.length > 64 ? `${normalized.slice(0, 61).trimEnd()}…` : normalized || 'Nueva conversación';
}

/** Serializa un turno como Markdown. Una sola implementación para «Copiar» y para exportar la conversación. */
export function turnToMarkdown(turn: AssistantTurn, level = 1): string {
  const heading = (offset: number) => '#'.repeat(Math.min(6, level + offset));
  const lines = [`${heading(0)} ${turn.question}`, ''];
  if (turn.topicId) lines.push(`Tema consultado: ${turn.topicTitle || turn.topicId}`, '');
  const result = turn.result;
  if (!result) {
    if (turn.state === 'interrupted') lines.push('_Consulta interrumpida al recargar. Puedes reintentarla desde Umbral._', '');
    else if (turn.state === 'pending') lines.push('_Consulta pendiente._', '');
    else lines.push(turn.error ?? 'La respuesta aún no está disponible.', '');
    return lines.join('\n');
  }
  if (result.resolvedQuestion) lines.push(`Pregunta interpretada: ${result.resolvedQuestion}`, '');
  if (turn.answerMode === 'modelo') lines.push(`Redactada con IA (${turn.composedBy ?? 'modelo'}) y verificada por código contra las fuentes; revisión humana pendiente.`, '');
  lines.push(`Estado: ${ANSWER_LABEL[result.answerStatus]}`, '', result.answer, '');
  if (result.abstentionReason && !result.answer.includes(result.abstentionReason)) lines.push(`Motivo de abstención: ${result.abstentionReason}`, '');
  if (result.missing.length) lines.push(`${heading(1)} Pendiente de verificar`, '', ...result.missing.map((item) => `- ${item}`), '');
  if (result.contradictions.length) {
    lines.push(`${heading(1)} Contradicciones`, '');
    for (const item of result.contradictions) lines.push(`- ${item.description}: ${item.versions.map((version) => `«${version.statement}» — ${version.outlet}`).join(' / ')}`);
    lines.push('');
  }
  if (result.citations.length) {
    lines.push(`${heading(1)} Fuentes`, '');
    for (const source of result.citations) lines.push(`- ${source.title ?? source.evidenceId}${source.url ? ` — ${source.url}` : ''} (${source.field})${source.passage ? `: «${source.passage}»` : ''}`);
    lines.push('');
  }
  lines.push(`Snapshot: ${result.snapshotId}`, `Versión de reglas: ${result.rulesVersion}`, '');
  return lines.join('\n');
}

export function exportAssistantMarkdown(conversation: AssistantConversation): string {
  const lines = [`# ${conversation.title}`, '', `Última actividad: ${conversation.updatedAt}`, ''];
  for (const turn of conversation.turns) lines.push(turnToMarkdown(turn, 2));
  return lines.join('\n');
}
