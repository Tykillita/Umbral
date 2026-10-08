import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { Bot, ChevronDown, Database, FileSearch, FlaskConical, ListOrdered, PenLine, WifiOff } from 'lucide-react';
import type { BootProgress, UmbralApi } from '../lib/api/client';
import { resolveApi } from '../lib/api';
import { initAuth, type AuthState } from '../lib/auth';
import { useRoute, type Route } from '../lib/router';
import { readLocal, writeLocal } from '../lib/storage';
import { useHealth, useRules } from '../lib/hooks';
import { DATA_MODE_LABEL } from '../lib/labels';
import { installInteractions } from '../lib/interactions';
import { useDisclosureMotion } from '../lib/useMotion';
import { fmtDateTime } from '../lib/format';
import { AppContext, useApp } from './context';
import { Agenda } from './views/Agenda';
import { Ficha } from './views/Ficha';
import { Drafts } from './views/Drafts';
import { Sources } from './views/Sources';
import { Assistant } from './Assistant';
import { Button, ErrorBox, Loading, Notice, Pill } from './ui';

const NAV: { view: Route['view']; label: string; icon: typeof ListOrdered; testId: string }[] = [
  { view: 'agenda', label: 'Agenda', icon: ListOrdered, testId: 'nav-agenda' },
  { view: 'ficha', label: 'Ficha', icon: FileSearch, testId: 'nav-ficha' },
  { view: 'borradores', label: 'Borradores', icon: PenLine, testId: 'nav-borradores' },
  { view: 'fuentes', label: 'Fuentes y evaluación', icon: Database, testId: 'nav-fuentes' },
];

function StatusItem({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  return (
    <div className="min-w-0 sm:flex sm:items-baseline sm:gap-1" data-testid={testId}>
      <dt className="text-ink-3">{label}</dt>
      <dd className="font-semibold">{children}</dd>
    </div>
  );
}

function StatusBar() {
  const { api, mockReason, authMode } = useApp();
  const { data: h, error } = useHealth();
  const rules = useRules();
  const [statusOpen, setStatusOpen] = useState(false);
  const detailsRef = useDisclosureMotion<HTMLDListElement>(statusOpen);
  return (
    <div className="space-y-2" data-testid="status-bar">
      {api.kind === 'mock' && (
        <Notice tone="amber" icon={FlaskConical} title="MODO DEMOSTRACIÓN del frontend: datos simulados, no son noticias ni cifras reales" testId="mock-banner" role="status">
          {mockReason} Para usar la API real, arranca el backend (puerto 8000) y define <code className="font-mono">PUBLIC_API_MODE=live</code>.
        </Notice>
      )}
      {error && api.kind === 'live' && (
        <div data-testid="api-down">
          <ErrorBox error={error} />
        </div>
      )}
      {h && (
        <button
          type="button"
          className="comic-button flex w-full items-center justify-between gap-2 px-3 text-left text-xs sm:hidden"
          aria-expanded={statusOpen}
          aria-controls="status-details"
          onClick={() => setStatusOpen(!statusOpen)}
          data-testid="status-toggle"
        >
          <span className="min-w-0 truncate">
            <span className="text-ink-3">Snapshot </span>
            <span className="font-mono font-semibold">{h.snapshotId}</span> · {DATA_MODE_LABEL[h.dataMode]}
          </span>
          <ChevronDown size={16} aria-hidden="true" className={`comic-chevron shrink-0 ${statusOpen ? 'rotate-180' : ''}`} />
        </button>
      )}
      {h && (
        <dl id="status-details" ref={detailsRef} className={`comic-statusbar ${statusOpen ? 'grid' : 'hidden'} grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-rule bg-card px-3 py-2 text-xs sm:flex sm:flex-wrap sm:items-center sm:gap-x-5`} aria-label="Estado de los datos">
          <StatusItem label="Snapshot">
            <span data-testid="snapshot-badge" className="font-mono [overflow-wrap:anywhere]">
              {h.snapshotId}
            </span>
          </StatusItem>
          <StatusItem label="Reglas">
            <span data-testid="rules-version" className="font-mono">
              {rules.data?.rulesVersion ?? h.rulesVersion}
            </span>
          </StatusItem>
          <StatusItem label="Corte" testId="snapshot-cutoff">
            {fmtDateTime(h.cutoffUtc)}
          </StatusItem>
          <StatusItem label="Clasificador">{h.classifier ?? 'sin clasificador'}</StatusItem>
          <StatusItem label="Acceso">
            {authMode === 'public' ? 'Público · trabajo guardado en este navegador' : (authMode === 'firebase-anonymous' ? 'Sesión anónima (Firebase)' : 'Usuario único local') + ' · ' + h.persistence}
          </StatusItem>
          <div className="col-span-2 flex flex-wrap items-center gap-1.5 sm:col-span-1">
            {h.offline && (
              <Pill tone="info" icon={WifiOff} testId="offline-indicator">
                Modo sin conexión: llamadas externas bloqueadas
              </Pill>
            )}
            <Pill tone={h.dataMode === 'congelado' ? 'ok' : 'warn'} testId="data-mode-banner" data-mode={h.dataMode}>
              {DATA_MODE_LABEL[h.dataMode]}
              {h.provisional && h.dataMode !== 'provisional' ? ' · provisional' : ''}
            </Pill>
          </div>
        </dl>
      )}
      {h && Date.now() - Date.parse(h.cutoffUtc) > 36 * 60 * 60 * 1000 && <Notice tone="warn" title="El corte tiene más de 36 horas" testId="stale-snapshot">Los datos disponibles siguen siendo el último corte válido. Revisa las fechas de las fuentes antes de usarlos.</Notice>}
      {h && (h.containsFixtures || h.dataMode === 'fixture') && (
        <Notice tone="warn" title="Este snapshot contiene datos de fixture" testId="fixture-notice">
          Sirven para probar el recorrido; no representan noticias ni indicadores reales. Se muestran etiquetados como tales.
        </Notice>
      )}
      {h?.classifier === 'laya' && (
        <Notice tone="warn" title="Clasificación automática sin calibración validada" testId="classification-limit">
          <span className="sm:hidden">Revisa la categoría y el impacto antes de usar el ranking.</span>
          <span className="hidden sm:inline">Laya puede asignar categorías erróneas y sus porcentajes no son confianza editorial: revisa categoría e impacto antes de usar el ranking.</span>
        </Notice>
      )}
      {h && h.integrity.errors.length > 0 && (
        <Notice tone="bad" title="Falló la verificación de integridad del snapshot" testId="integrity-errors" role="alert">
          {h.integrity.errors.join(' · ')}
        </Notice>
      )}
    </div>
  );
}

function Shell({ assistantOpen, setAssistantOpen, seed }: { assistantOpen: boolean; setAssistantOpen: (v: boolean) => void; seed: { text: string; n: number } }) {
  const { route, go } = useApp();
  const [mobile, setMobile] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  const lastTopic = useRef<string | null>(null);
  if ('topicId' in route && route.topicId) lastTopic.current = route.topicId;

  // Respuesta táctil global (pulsación, trazos y detalles); se retira al desmontar la aplicación.
  useEffect(() => installInteractions(), []);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 1023px)');
    const update = () => setMobile(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  // Mover el foco al contenido principal al cambiar de vista (accesibilidad de SPA).
  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, [route.view]);

  return (
    <div data-testid="app-root" className={assistantOpen ? 'lg:pr-[26rem]' : ''}>
      <a href="#contenido" inert={assistantOpen && mobile} className="skip-link">
        Saltar al contenido
      </a>
      <header inert={assistantOpen && mobile} className="comic-masthead @container sticky top-0 z-30 border-b-2 border-ink no-print">
        <div className="mx-auto flex max-w-6xl items-center gap-x-6 px-4 py-2 md:grid md:grid-cols-[1fr_auto_1fr] md:gap-x-4">
          <a href="/" className="comic-brand md:justify-self-start" aria-label="Umbral, inicio">
            Umbral<span className="text-amber-600">.</span>
          </a>
          <nav aria-label="Vistas principales" className="comic-tabbar flex gap-1 md:justify-center">
            {NAV.map(({ view, label, icon: Ico, testId }) => {
              const active = route.view === view;
              return (
                <a
                  key={view}
                  href={`#/${view}`}
                  data-testid={testId}
                  aria-current={active ? 'page' : undefined}
                  onClick={(e) => {
                    e.preventDefault();
                    go(view === 'agenda' || view === 'fuentes' ? { view } : { view, topicId: lastTopic.current });
                  }}
                  className={`comic-nav inline-flex min-h-11 shrink-0 items-center gap-1.5 px-3 py-1.5 text-sm font-semibold ${
                    active ? 'border-amber-600 bg-amber-100 text-ink' : 'border-transparent text-ink-2 hover:bg-sunk'
                  }`}
                >
                  <Ico size={16} aria-hidden="true" />
                  {label === 'Fuentes y evaluación' ? (
                    <>
                      <span className="@5xl:hidden">Fuentes</span>
                      <span className="hidden @5xl:inline">{label}</span>
                    </>
                  ) : (
                    label
                  )}
                </a>
              );
            })}
          </nav>
          <Button
            variant={assistantOpen ? 'primary' : 'secondary'}
            icon={Bot}
            onClick={() => setAssistantOpen(!assistantOpen)}
            aria-expanded={assistantOpen}
            aria-controls="assistant-panel"
            data-testid="assistant-toggle"
            className="ml-auto md:ml-0 md:justify-self-end"
          >
            <span className="@max-3xl:sr-only">Asistente</span>
          </Button>
        </div>
      </header>

      <main id="contenido" inert={assistantOpen && mobile} ref={mainRef} tabIndex={-1} className="comic-sheet mx-auto max-w-6xl space-y-4 px-4 pb-24 pt-5 outline-none md:pb-5">
        <StatusBar />
        <div key={route.view} className="pt-1">
          {route.view === 'agenda' && <Agenda />}
          {route.view === 'ficha' && <Ficha />}
          {route.view === 'borradores' && <Drafts />}
          {route.view === 'fuentes' && <Sources />}
        </div>
        <footer className="mt-8 border-t border-rule pt-3 text-xs text-ink-3">
          Umbral prioriza la atención editorial y prepara borradores para revisión humana. No publica, no etiqueta noticias como verdaderas o falsas y no sustituye el criterio del equipo.
        </footer>
      </main>
      <Assistant open={assistantOpen} modal={mobile} onClose={() => setAssistantOpen(false)} seed={seed} />
    </div>
  );
}

type Boot = { api: UmbralApi; reason: string | null; auth: AuthState };

function Inner() {
  const queryClient = useQueryClient();
  const [bootAttempt, setBootAttempt] = useState(0);
  const [progress, setProgress] = useState<BootProgress | null>(null);
  const [boot, setBoot] = useState<Boot | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [route, go] = useRoute();
  const [reviewer, setReviewerState] = useState(() => readLocal('umbral.reviewer', ''));
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [seed, setSeed] = useState({ text: '', n: 0 });

  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    let activeApi: UmbralApi | null = null;
    setBootError(null);
    setProgress(null);
    (async () => {
      try {
        const auth = await initAuth();
        if (auth.error) throw new Error(auth.error);
        const r = await resolveApi((next) => { if (live) setProgress(next); }, controller.signal); activeApi = r.api;
        if (live) setBoot({ api: r.api, reason: r.reason, auth }); else await r.api.close?.();
      } catch (e) {
        if (live) setBootError(e instanceof Error ? e.message : 'Error de arranque');
      }
    })();
    return () => {
      live = false;
      controller.abort();
      void activeApi?.close?.();
    };
  }, [bootAttempt]);

  useEffect(() => boot?.api.subscribe?.(() => { void Promise.all(['topics','topic','rules','workspace-cases'].map((key) => queryClient.invalidateQueries({ queryKey: [key] }))); }), [boot, queryClient]);

  const setReviewer = useCallback((name: string) => {
    setReviewerState(name);
    writeLocal('umbral.reviewer', name);
  }, []);
  const openAssistant = useCallback((prompt?: string) => {
    setAssistantOpen(true);
    if (prompt) setSeed((s) => ({ text: prompt, n: s.n + 1 }));
  }, []);

  const ctx = useMemo(
    () =>
      boot
        ? {
            api: boot.api,
            mockReason: boot.reason,
            route,
            go,
            reviewer,
            setReviewer,
            openAssistant,
            authMode: boot.auth.mode,
          }
        : null,
    [boot, route, go, reviewer, setReviewer, openAssistant],
  );

  if (bootError) return <div className="mx-auto max-w-xl p-6" data-testid="app-boot-error"><ErrorBox error={new Error(bootError)} onRetry={() => setBootAttempt((value) => value + 1)} /></div>;
  if (!ctx) return <div className="mx-auto max-w-xl p-6" data-testid="app-loading"><Loading label={progress?.message ?? "Iniciando Umbral…"} />{progress && <p className="text-sm text-ink-3" aria-live="polite">Intento {progress.attempt} · {Math.floor(progress.elapsedMs / 1000)} s. El primer inicio puede tardar hasta 90 segundos.</p>}</div>;
  return (
    <AppContext.Provider value={ctx}>
      <Shell assistantOpen={assistantOpen} setAssistantOpen={setAssistantOpen} seed={seed} />
    </AppContext.Provider>
  );
}

export default function App() {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: 1 } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Inner />
    </QueryClientProvider>
  );
}
