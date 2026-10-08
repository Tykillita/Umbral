export const PANAMA_TZ = 'America/Panama';

const fmtFull = new Intl.DateTimeFormat('es-PA', {
  timeZone: PANAMA_TZ,
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const fmtDay = new Intl.DateTimeFormat('es-PA', { timeZone: PANAMA_TZ, day: 'numeric', month: 'short', year: 'numeric' });

/** Fecha/hora UTC (ISO) → texto en hora de Panamá (UTC-5). `null` → «fecha desconocida». */
export function fmtDateTime(iso: string | null | undefined, unknown = 'fecha desconocida'): string {
  if (!iso) return unknown;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return unknown;
  return `${fmtFull.format(d)} (hora de Panamá)`;
}

export function fmtDate(iso: string | null | undefined, unknown = 'fecha desconocida'): string {
  if (!iso) return unknown;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? unknown : fmtDay.format(d);
}

export function fmtScore(n: number): string {
  return n.toLocaleString('es-PA', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export function fmtNumber(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined) return '—';
  return n.toLocaleString('es-PA', { maximumFractionDigits: digits });
}

export function pct(n: number): string {
  return `${Math.round(n * 100)} %`;
}

export function shortHash(h: string | null | undefined, n = 12): string {
  return h ? `${h.slice(0, n)}…` : '—';
}
