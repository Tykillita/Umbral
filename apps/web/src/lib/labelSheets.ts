import type { LabelType } from './team';

export interface SheetSource {
  id: string;
  text: string;
  outlet: string;
  url: string;
  publishedAt: string | null;
  detectedAt: string | null;
}
export interface SheetPair {
  id: string;
  a: SheetSource;
  b: SheetSource;
}
export interface SheetCitation {
  evidenceId: string;
  field: string;
  passage: string | null;
  title: string | null;
  outlet: string | null;
  url: string | null;
  publishedAt: string | null;
  detectedAt: string | null;
}
export interface SheetClaim {
  id: string;
  text: string;
  citations: SheetCitation[];
}
export interface LabelSheets {
  version: 1;
  snapshotId: string;
  sheetHash: string;
  topics: SheetSource[];
  pairs: SheetPair[];
  claims: SheetClaim[];
}
export type SheetItem = SheetSource | SheetPair | SheetClaim;
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object')
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`)
      .join(',')}}`;
  return JSON.stringify(value);
}
function text(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 16000;
}
function date(value: unknown): boolean {
  return value === null || (text(value) && Number.isFinite(Date.parse(value)));
}
function source(value: unknown): value is SheetSource {
  if (!value || typeof value !== 'object') return false;
  const s = value as SheetSource;
  return (
    text(s.id) &&
    Boolean(s.id) &&
    text(s.text) &&
    text(s.outlet) &&
    text(s.url) &&
    date(s.publishedAt) &&
    date(s.detectedAt)
  );
}
function citation(value: unknown): value is SheetCitation {
  if (!value || typeof value !== 'object') return false;
  const c = value as SheetCitation;
  return (
    text(c.evidenceId) &&
    text(c.field) &&
    ['passage', 'title', 'outlet', 'url'].every(
      (key) => c[key as keyof SheetCitation] === null || text(c[key as keyof SheetCitation]),
    ) &&
    date(c.publishedAt) &&
    date(c.detectedAt)
  );
}
export async function parseSheets(value: unknown): Promise<LabelSheets> {
  if (!value || typeof value !== 'object')
    throw new Error('Las hojas de etiquetado tienen un formato incompatible.');
  const h = value as LabelSheets;
  if (
    h.version !== 1 ||
    !text(h.snapshotId) ||
    !h.snapshotId ||
    !/^[0-9a-f]{64}$/.test(h.sheetHash) ||
    !Array.isArray(h.topics) ||
    !h.topics.every(source) ||
    !Array.isArray(h.pairs) ||
    !h.pairs.every((p) => text(p.id) && Boolean(p.id) && source(p.a) && source(p.b)) ||
    !Array.isArray(h.claims) ||
    !h.claims.every(
      (c) =>
        text(c.id) &&
        Boolean(c.id) &&
        text(c.text) &&
        Array.isArray(c.citations) &&
        c.citations.every(citation),
    ) ||
    [h.topics, h.pairs, h.claims].some((items) => new Set(items.map((item) => item.id)).size !== items.length)
  )
    throw new Error('Las hojas de etiquetado no cumplen el contrato de versión 1.');
  const { sheetHash, ...payload } = h;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(payload)));
  const actual = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  if (actual !== sheetHash)
    throw new Error(
      'Las hojas cambiaron o están incompletas: su huella no coincide. Recarga una copia íntegra antes de etiquetar.',
    );
  // Construir las entradas visibles solo con evidencia: nunca propagar campos de predicciones.
  const safeSource = (s: SheetSource): SheetSource => ({
    id: s.id,
    text: s.text,
    outlet: s.outlet,
    url: s.url,
    publishedAt: s.publishedAt,
    detectedAt: s.detectedAt,
  });
  return {
    version: 1,
    snapshotId: h.snapshotId,
    sheetHash,
    topics: h.topics.map(safeSource),
    pairs: h.pairs.map((p) => ({ id: p.id, a: safeSource(p.a), b: safeSource(p.b) })),
    claims: h.claims.map((c) => ({
      id: c.id,
      text: c.text,
      citations: c.citations.map((v) => ({
        evidenceId: v.evidenceId,
        field: v.field,
        passage: v.passage,
        title: v.title,
        outlet: v.outlet,
        url: v.url,
        publishedAt: v.publishedAt,
        detectedAt: v.detectedAt,
      })),
    })),
  };
}
export async function fetchSheets(): Promise<LabelSheets> {
  const response = await fetch('/etiquetado/hojas.json', {
    credentials: 'omit',
    cache: 'no-store',
    headers: { Accept: 'application/json' },
  });
  if (!response.ok)
    throw new Error(
      'No se pudieron cargar las hojas de etiquetado del corte. Reintenta cuando estén disponibles.',
    );
  return parseSheets(await response.json());
}
export function sheetItems(sheets: LabelSheets, type: LabelType): SheetItem[] {
  return type === 'topic' ? sheets.topics : type === 'pair' ? sheets.pairs : sheets.claims;
}
