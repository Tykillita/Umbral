import { useEffect, useId, useState } from 'react';
import { ArrowUpRight, Clock3, Newspaper, RefreshCw } from 'lucide-react';
import type { NewsRefreshResponse } from '../../lib/api/types';
import { describeError, isServiceUnavailable } from '../../lib/api/client';
import { fmtDate, fmtDateTime } from '../../lib/format';
import { useHealth, useRefreshNews, useToday } from '../../lib/hooks';
import { JURY_DEMO_CUTOFF_UTC, JURY_DEMO_ITEMS, JURY_DEMO_SNAPSHOT } from '../../lib/juryDemo';
import { useApp } from '../context';
import { Button, Notice } from '../ui';

/** «hace 25 min», «hace 3 h»: la hora exacta de Panamá va al lado. */
function ago(iso: string, now = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return 'hace un momento';
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  return `hace ${hours} h`;
}

const REFRESH_KEY = 'umbral.news-refresh.v1';
const REFRESH_MAX_AGE_MS = 6 * 3600_000;

interface StoredRefresh {
  at: number;
  snapshotId: string;
  response: NewsRefreshResponse;
}

function readRefresh(): StoredRefresh | null {
  try {
    const raw = window.sessionStorage.getItem(REFRESH_KEY);
    const value = raw ? (JSON.parse(raw) as StoredRefresh) : null;
    return value && Date.now() - value.at < REFRESH_MAX_AGE_MS ? value : null;
  } catch {
    return null;
  }
}

function writeRefresh(value: StoredRefresh | null): void {
  try {
    if (value) window.sessionStorage.setItem(REFRESH_KEY, JSON.stringify(value));
    else window.sessionStorage.removeItem(REFRESH_KEY);
  } catch {
    /* sin almacenamiento: el aviso solo dura mientras la vista siga abierta */
  }
}

const CLASSIFICATION_TITLE: Record<string, string> = {
  solicitada: 'Clasificación en curso',
  en_curso: 'Clasificación en curso',
  enfriamiento: 'Clasificación ya solicitada',
  no_disponible: 'Clasificación no disponible por ahora',
  error: 'No se pudo pedir la clasificación',
};

/** Resultado de «Actualizar noticias»: lo recién consultado va SIN clasificar y se dice cuánto puede tardar la clasificación. */
function RefreshResult({ stored }: { stored: StoredRefresh }) {
  const { response } = stored;
  const pending = response.classification.status === 'solicitada' || response.classification.status === 'en_curso' || response.classification.status === 'enfriamiento';
  return (
    <div className="mt-3 space-y-3" data-testid="today-refresh-result">
      <Notice tone="info" title={CLASSIFICATION_TITLE[response.classification.status] ?? 'Clasificación'} testId="today-classification" role="status">
        {response.classification.message}
        {response.classification.runUrl && (
          <>
            {' '}
            <a href={response.classification.runUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-semibold underline underline-offset-4">
              Ver el avance <ArrowUpRight size={14} strokeWidth={2.6} aria-hidden="true" />
            </a>
          </>
        )}
      </Notice>
      <div>
        <p className="kicker">Noticias recién consultadas · sin clasificar</p>
        <p className="mb-2 text-xs text-ink-3">
          Consultadas {ago(response.checkedAt)}. {pending ? 'Aún no están en la agenda ni en el puntaje: entran cuando termine la clasificación.' : 'No están en la agenda ni en el puntaje.'}
        </p>
        {response.items.length === 0 ? (
          <p className="text-sm text-ink-2" data-testid="today-live-empty">No se encontraron titulares publicados en las últimas 24 horas en las fuentes consultadas.</p>
        ) : (
          <ul className="grid gap-2 md:grid-cols-2" data-testid="today-live-list">
            {response.items.map((item) => (
              <li key={item.id} data-testid="today-live-item" className="min-w-0 border-2 border-dashed border-ink bg-paper p-3">
                <p className="mb-1 flex flex-wrap items-center gap-x-2 text-xs text-ink-3">
                  <span className="border border-ink bg-amber-100 px-1.5 py-0.5 font-bold text-ink">Sin clasificar</span>
                  <span>{item.outlet}</span>
                </p>
                <p className="font-display text-lg font-bold leading-tight">{item.title}</p>
                <p className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-3">
                  <span><strong className="text-ink-2">{ago(item.publishedAt)}</strong> · {fmtDateTime(item.publishedAt)}</span>
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="comic-link inline-flex items-center gap-1 font-semibold underline underline-offset-4"
                    aria-label={`Abrir la fuente original en ${item.outlet} (se abre en otra pestaña)`}
                  >
                    Fuente <ArrowUpRight size={14} strokeWidth={2.6} aria-hidden="true" />
                  </a>
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/**
 * «Hoy»: los 5 titulares más recientes de las últimas 24 horas. Va aparte del puntaje (`scoring-v1`): ordena por publicación,
 * no por prioridad. Solo cuenta lo que trae fecha de publicación; una fecha de detección no es una publicación.
 */
export function TodaySection({ onOpen }: { onOpen: (topicId: string) => void }) {
  const uid = useId();
  const today = useToday();
  const { data, error, isLoading } = today;
  const health = useHealth().data;
  const refresh = useRefreshNews();
  const [stored, setStored] = useState<StoredRefresh | null>(readRefresh);
  // Cuando llega un corte nuevo la agenda y «Hoy» ya traen lo clasificado: lo «sin clasificar» deja de hacer falta.
  useEffect(() => {
    if (stored && health && health.snapshotId !== stored.snapshotId) {
      writeRefresh(null);
      setStored(null);
    }
  }, [health, stored]);
  const run = () =>
    refresh.mutate(undefined, {
      onSuccess: (response) => {
        const next = { at: Date.now(), snapshotId: health?.snapshotId ?? '', response };
        writeRefresh(next);
        setStored(next);
      },
    });
  return (
    <section className="comic-panel p-4" aria-labelledby={`${uid}-today-title`} data-testid="agenda-today" aria-busy={today.isFetching}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2 border-b-2 border-ink pb-3">
        <div className="flex items-center gap-2">
          <Clock3 size={19} className="text-amber-700" aria-hidden="true" />
          <div>
            <p className="kicker">Últimas 24 horas · fuera del puntaje</p>
            <h2 id={`${uid}-today-title`} className="font-display text-xl font-bold">Hoy: lo más reciente</h2>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {data && <p className="text-xs text-ink-3">Consulta: {fmtDateTime(data.checkedAt)}</p>}
          <Button icon={RefreshCw} busy={refresh.isPending} onClick={run} disabled={refresh.isPending} data-testid="today-refresh">
            Actualizar noticias
          </Button>
        </div>
      </div>
      <p className="sr-only" aria-live="polite">{refresh.isPending ? 'Consultando las noticias más recientes…' : ''}</p>
      {refresh.error && (
        <p className="mb-2 text-sm text-ink-2" role="status" data-testid="today-refresh-error">
          {isServiceUnavailable(refresh.error) ? 'El servicio no está disponible ahora; inténtalo de nuevo en un minuto.' : describeError(refresh.error)}
        </p>
      )}
      {isLoading && <p aria-live="polite" className="py-2 text-sm text-ink-3">Buscando lo más reciente…</p>}
      {error && (
        <p className="py-2 text-sm text-ink-3" role="status" data-testid="today-unavailable">
          {isServiceUnavailable(error) ? 'Lo más reciente no está disponible ahora; aparecerá cuando el servicio vuelva a responder.' : 'No se pudo consultar lo más reciente.'}
        </p>
      )}
      {data && data.items.length > 0 && (
        <ol className="grid gap-2 md:grid-cols-2" aria-label="Los cinco titulares más recientes" data-testid="today-list">
          {data.items.map((item) => (
            <li key={item.id} data-testid="today-item" className="min-w-0 border-2 border-ink bg-paper p-3 shadow-[3px_3px_0_var(--color-ink)]">
              <p className="mb-1 flex flex-wrap items-center gap-x-2 text-xs text-ink-3">
                <span className="font-bold text-ink-2">{item.categoryLabel}</span>
                <span aria-hidden="true">·</span>
                <span>{item.outlet}</span>
              </p>
              <button type="button" onClick={() => onOpen(item.id)} className="comic-link block w-full text-left font-display text-lg font-bold leading-tight underline-offset-4 hover:underline">
                {item.title}
              </button>
              <p className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-3">
                <span><strong className="text-ink-2">{ago(item.publishedAt)}</strong> · {fmtDateTime(item.publishedAt)}</span>
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="comic-link inline-flex items-center gap-1 font-semibold underline underline-offset-4"
                  aria-label={`Abrir la fuente original en ${item.outlet} (se abre en otra pestaña)`}
                >
                  Fuente <ArrowUpRight size={14} strokeWidth={2.6} aria-hidden="true" />
                </a>
              </p>
            </li>
          ))}
        </ol>
      )}
      {data && data.items.length === 0 && (
        <p className="text-sm text-ink-2" role="status" data-testid="today-empty">
          {data.note ?? 'No hay noticias con fecha de publicación en las últimas 24 horas.'}
        </p>
      )}
      {data && data.items.length > 0 && data.note && <p className="mt-2 text-xs text-ink-3">{data.note}</p>}
      {stored && <RefreshResult stored={stored} />}
    </section>
  );
}

/** La agenda queda vacía hasta que llegue un corte vigente: se dice por qué, sin rellenar con noticias viejas. */
export function EmptyNewsPanel() {
  const health = useHealth().data;
  const { session } = useApp();
  const hidden = health?.hiddenSnapshotId;
  return (
    <div className="space-y-4" data-testid="agenda-no-news">
      <Notice tone="info" icon={Newspaper} title="Aún no hay noticias vigentes" testId="agenda-no-news-notice">
        {hidden
          ? `El último corte disponible (${hidden}, del ${fmtDate(health?.hiddenSnapshotCutoffUtc)}) es demasiado antiguo y no se muestra. `
          : 'Todavía no se ha publicado un corte de noticias. '}
        Las noticias se actualizan cada 6 horas; en cuanto llegue un corte nuevo, la agenda se llena sola. El sistema no rellena la agenda con noticias viejas ni inventadas.
      </Notice>
      {session?.role === 'juror' && <JuryDemoPanel />}
    </div>
  );
}

/** Solo para el rol Jurado: unos pocos titulares reales de un corte anterior, rotulados como demostración. */
export function JuryDemoPanel() {
  const uid = useId();
  return (
    <section className="comic-panel p-4" aria-labelledby={`${uid}-demo-title`} data-testid="jury-demo">
      <div className="mb-3 border-b-2 border-ink pb-3">
        <p className="kicker">Demostración para el jurado</p>
        <h2 id={`${uid}-demo-title`} className="font-display text-xl font-bold">Titulares de muestra de un corte anterior</h2>
        <p className="mt-1 text-sm text-ink-2">
          Cinco titulares reales del corte {JURY_DEMO_SNAPSHOT} (provisional, {fmtDate(JURY_DEMO_CUTOFF_UTC)}), solo para recorrer la solución. No son noticias de hoy
          ni entran en la agenda, el puntaje ni la evaluación.
        </p>
      </div>
      <ul className="grid gap-2 md:grid-cols-2">
        {JURY_DEMO_ITEMS.map((item) => (
          <li key={item.id} data-testid="jury-demo-item" className="min-w-0 border-2 border-ink bg-paper p-3 shadow-[3px_3px_0_var(--color-ink)]">
            <p className="mb-1 text-xs text-ink-3"><span className="font-bold text-ink-2">{item.categoryLabel}</span> · {item.outlet}</p>
            <p className="font-display text-lg font-bold leading-tight">{item.title}</p>
            <p className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-3">
              <span>{fmtDateTime(item.publishedAt)}</span>
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="comic-link inline-flex items-center gap-1 font-semibold underline underline-offset-4"
                aria-label={`Abrir la fuente original en ${item.outlet} (se abre en otra pestaña)`}
              >
                Fuente <ArrowUpRight size={14} strokeWidth={2.6} aria-hidden="true" />
              </a>
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
