import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { Bot, ChevronDown, CircleAlert, CircleCheck, CircleX, Database, ExternalLink, FileSearch, FlaskConical, ListOrdered, LoaderCircle, PenLine, Tags, Users, WifiOff, X } from 'lucide-react';
import type { BootProgress, UmbralApi } from '../lib/api/client';
import { resolveApi } from '../lib/api';
import { initAuth, type AuthState } from '../lib/auth';
import { useRoute, type Route } from '../lib/router';
import { canView, chooseRole, defaultRoute, readSession, type DemoRole } from '../lib/session';
import { roleApi } from '../lib/roleApi';
import { readLocal, writeLocal } from '../lib/storage';
import { useHealth, useRules } from '../lib/hooks';
import { DATA_MODE_LABEL } from '../lib/labels';
import { installInteractions } from '../lib/interactions';
import { reducedMotion } from '../lib/motion';
import { useDisclosureMotion } from '../lib/useMotion';
import { fmtDateTime } from '../lib/format';
import { AppContext, useApp, type AppToast } from './context';
import { Agenda } from './views/Agenda';
import { Ficha } from './views/Ficha';
import { Drafts } from './views/Drafts';
import { Sources } from './views/Sources';
import { Mesa } from './views/Mesa';
import { Etiquetar } from './views/Etiquetar';
import { SessionGate } from './SessionGate';
import { AssistantPanel } from './AssistantPanel';
import { Button, ErrorBox, Loading, Notice, Pill } from './ui';
import { SettingsPanel } from './SettingsPanel';
import { WarningCenter, WarningCenterProvider } from './ui/warnings';
import { Select } from './ui/controls';

const NAV: { view: Route['view']; label: string; icon: typeof ListOrdered; testId: string }[] = [
  { view: 'agenda', label: 'Agenda', icon: ListOrdered, testId: 'nav-agenda' },
  { view: 'ficha', label: 'Ficha', icon: FileSearch, testId: 'nav-ficha' },
  { view: 'borradores', label: 'Borradores', icon: PenLine, testId: 'nav-borradores' },
  { view: 'fuentes', label: 'Fuentes y evaluación', icon: Database, testId: 'nav-fuentes' },
  { view: 'mesa', label: 'Mesa', icon: Users, testId: 'nav-mesa' },
  { view: 'etiquetar', label: 'Etiquetar', icon: Tags, testId: 'nav-etiquetar' },
];

export function SnapshotDataRefresh({ snapshotId }: { snapshotId?: string }) {
  const queryClient = useQueryClient();
  const previousSnapshotId = useRef<string | null>(null);
  useEffect(() => {
    if (!snapshotId) return;
    const previous = previousSnapshotId.current;
    previousSnapshotId.current = snapshotId;
    if (!previous || previous === snapshotId) return;
    void Promise.all(['snapshot', 'topics', 'topic'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })));
  }, [queryClient, snapshotId]);
  return null;
}

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
      {h && h.integrity.errors.length > 0 && (
        <Notice tone="bad" title="Falló la verificación de integridad del snapshot" testId="integrity-errors" role="alert">
          {h.integrity.errors.join(' · ')}
        </Notice>
      )}
    </div>
  );
}

type AssistantVisibility = 'closed' | 'minimized' | 'open';

export function ExportToast({ toast, anchor, onDismiss }: { toast: AppToast | null; anchor: 'dock' | 'toggle'; onDismiss: () => void }) {
  const [paused, setPaused] = useState(false);
  const duration = toast?.durationMs ?? (toast?.tone === 'error' ? 9_000 : 6_500);

  useEffect(() => {
    setPaused(false);
  }, [toast?.id]);

  useEffect(() => {
    if (!toast || toast.tone === 'pending' || paused) return;
    const timer = window.setTimeout(onDismiss, duration);
    return () => window.clearTimeout(timer);
  }, [duration, onDismiss, paused, toast?.id, toast?.tone]);

  if (!toast) return null;
  const Icon = toast.tone === 'pending' ? LoaderCircle : toast.tone === 'success' ? CircleCheck : toast.tone === 'error' ? CircleX : CircleAlert;
  const style = {
    '--toast-lifetime': `${duration}ms`,
    '--toast-progress': toast.progress == null ? undefined : String(Math.max(0, Math.min(100, toast.progress)) / 100),
  } as CSSProperties & { '--toast-lifetime': string; '--toast-progress': string | undefined };
  return (
    <section
      className="export-toast"
      data-testid="export-toast"
      data-tone={toast.tone}
      data-anchor={anchor}
      data-download-progress={toast.progress != null || undefined}
      data-autohide={toast.tone !== 'pending' && !paused || undefined}
      role={toast.tone === 'error' ? 'alert' : 'status'}
      aria-live={toast.tone === 'error' ? 'assertive' : 'polite'}
      aria-atomic="true"
      aria-busy={toast.tone === 'pending' || undefined}
      style={style}
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setPaused(false);
      }}
    >
      <Icon className="export-toast-icon" size={20} aria-hidden="true" />
      <div className="export-toast-copy">
        <strong>{toast.title}</strong>
        {toast.description && <span>{toast.description}</span>}
      </div>
      {toast.actionHref && toast.actionLabel && (
        <a className="export-toast-action" href={toast.actionHref} target="_blank" rel="noopener noreferrer">
          {toast.actionLabel}<ExternalLink size={14} aria-hidden="true" />
        </a>
      )}
      <button type="button" className="export-toast-close" aria-label="Cerrar aviso" onClick={onDismiss}>
        <X size={18} aria-hidden="true" />
      </button>
      <span className="export-toast-progress" aria-hidden="true" />
    </section>
  );
}

function Shell({ assistantState, setAssistantState, assistantClosing, openAssistantPanel, closeAssistantPanel, seed, assistantUnread, onAssistantUnread }: { assistantUnread: number; onAssistantUnread: (count: number) => void; assistantState: AssistantVisibility; setAssistantState: (v: AssistantVisibility) => void; assistantClosing: boolean; openAssistantPanel: () => void; closeAssistantPanel: () => void; seed: { text: string; topicId: string | null; topicTitle: string; n: number } }) {
  const { route, go, toast, showToast, dismissToast, session, changeRole } = useApp();
  const navigation = NAV.filter(({view}) => !session || canView(session.role,view));
  const mobilePrimaryViews: Route['view'][] = ['agenda', 'ficha', 'borradores', 'fuentes'];
  const mobileOverflow = navigation.filter(({view}) => !mobilePrimaryViews.includes(view));
  const mobileNavColumns = navigation.filter(({view}) => mobilePrimaryViews.includes(view)).length + (mobileOverflow.length ? 1 : 0);
  const [mobile, setMobile] = useState(false);
  const [warningCenterOpen, setWarningCenterOpen] = useState(false);
  const { data: health } = useHealth();
  const mainRef = useRef<HTMLElement>(null);
  const mastheadRef = useRef<HTMLElement>(null);
  const lastTopic = useRef<string | null>(null);
  if ('topicId' in route && route.topicId) lastTopic.current = route.topicId;
  const navigateToView = (view: Route['view']) => {
    go(view === 'ficha' || view === 'borradores' ? { view, topicId: lastTopic.current } : { view });
  };

  // Respuesta táctil global (pulsación, trazos y detalles); se retira al desmontar la aplicación.
  useEffect(() => installInteractions(), []);

  useEffect(() => {
    const subscribe = window.umbralDesktop?.onDownloadStatus;
    if (!subscribe) return;
    return subscribe((download) => {
      const filename = download.filename;
      if (download.status === 'completed') {
        showToast({ tone: 'success', title: 'Descarga completada', description: `${filename} se guardó correctamente.`, progress: 100 });
      } else if (download.status === 'error') {
        showToast({ tone: 'error', title: 'Error en la descarga', description: `No se pudo guardar ${filename}. Revisa la carpeta Descargas y el espacio disponible.` });
      } else {
        const progress = download.status === 'started' ? 0 : download.percent;
        showToast({
          tone: 'pending',
          title: download.status === 'started' ? 'Iniciando descarga' : 'Descargando Markdown',
          description: `${filename}${progress == null ? '' : ` · ${progress}%`}`,
          progress,
        });
      }
    });
  }, [showToast]);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 1023px)');
    const update = () => setMobile(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    const header = mastheadRef.current;
    if (!header) return;
    const measure = () => document.documentElement.style.setProperty('--assistant-top', `${Math.ceil(header.getBoundingClientRect().bottom + 16)}px`);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(header);
    window.addEventListener('resize', measure);
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => { frame = 0; measure(); });
    };
    window.addEventListener('scroll', onScroll, { passive: true, capture: true });
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', onScroll, { capture: true });
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  const assistantOpen = assistantState === 'open' && !assistantClosing;

  // Mover el foco al contenido principal al cambiar de vista (accesibilidad de SPA).
  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true });
    mainRef.current?.scrollTo({ top: 0, left: 0, behavior: 'auto' });
    window.scrollTo({ top: 0 });
    document.body.scrollTo({ top: 0 });
  }, [route.view]);

  return (
    <div data-testid="app-root" inert={warningCenterOpen || undefined}>
      <SnapshotDataRefresh snapshotId={health?.snapshotId} />
      <SettingsPanel />
      <a href="#contenido" inert={assistantOpen && mobile} className="skip-link">
        Saltar al contenido
      </a>
      <header ref={mastheadRef} inert={assistantOpen && mobile} className="comic-masthead @container sticky top-0 z-30 border-b-2 border-ink no-print">
        <div className="comic-app-header w-full px-4 py-2">
          <a href="/" className="comic-brand md:justify-self-start" aria-label="Umbral, inicio">
            Umbral<span className="text-amber-600">.</span>
          </a>
          <nav aria-label="Vistas principales" className="comic-tabbar flex gap-1 md:justify-center" style={{'--nav-count':navigation.length, '--mobile-nav-count':mobileNavColumns} as CSSProperties}>
            {navigation.map(({ view, label, icon: Ico, testId }) => {
              const active = route.view === view;
              return (
                <a
                  key={view}
                  href={`#/${view}`}
                  data-testid={testId}
                  aria-current={active ? 'page' : undefined}
                  onClick={(e) => {
                    e.preventDefault();
                    navigateToView(view);
                  }}
                  className={`comic-nav inline-flex min-h-11 shrink-0 items-center gap-1.5 px-3 py-1.5 text-sm font-semibold ${
                    mobilePrimaryViews.includes(view) ? '' : 'comic-nav-overflow'
                  } ${
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
            {mobileOverflow.length > 0 && (
              <div className="comic-tabbar-more">
                <Select
                  label="Más vistas"
                  testId="nav-more"
                  value={mobileOverflow.some(({ view }) => view === route.view) ? route.view : ''}
                  onChange={navigateToView}
                  options={mobileOverflow.map(({ view, label }) => ({ value: view, label }))}
                  placeholder="Más"
                  className="comic-mobile-more-trigger"
                />
              </div>
            )}
          </nav>
          <div className="comic-header-actions ml-auto flex shrink-0 items-center gap-2 md:ml-0 md:justify-self-end">
            {session && <div className="comic-active-role"><span data-testid="active-role">{session.labeler}</span><Button variant="ghost" onClick={changeRole} data-testid="role-change">Cambiar</Button></div>}
            <WarningCenter open={warningCenterOpen} onOpenChange={setWarningCenterOpen} layaActive={health?.classifier === 'laya'} />
            <Button
              variant={assistantOpen ? 'primary' : 'secondary'}
              icon={Bot}
              onClick={() => assistantOpen ? closeAssistantPanel() : openAssistantPanel()}
              aria-expanded={assistantOpen}
              aria-controls={assistantState !== 'closed' ? 'assistant-panel' : undefined}
              data-testid="assistant-toggle"
              className="ml-auto md:ml-0 md:justify-self-end"
            >
              <span className="@max-3xl:sr-only">Asistente</span>
              {assistantUnread > 0 && !assistantOpen && (
                <>
                  <span className="assistant-unread ml-1" aria-hidden="true" data-testid="assistant-toggle-unread">{assistantUnread}</span>
                  <span className="sr-only">{assistantUnread === 1 ? ', 1 respuesta nueva' : `, ${assistantUnread} respuestas nuevas`}</span>
                </>
              )}
            </Button>
          </div>
        </div>
      </header>

      <main id="contenido" inert={assistantOpen && mobile} ref={mainRef} tabIndex={-1} className="comic-sheet mx-auto max-w-6xl space-y-4 px-4 pb-24 pt-5 outline-none md:pb-5">
        <StatusBar />
        <div key={route.view} className="pt-1">
          {route.view === 'agenda' && <Agenda />}
          {route.view === 'ficha' && <Ficha />}
          {route.view === 'borradores' && <Drafts />}
          {route.view === 'fuentes' && <Sources />}
          {route.view === 'mesa' && <Mesa />}
          {route.view === 'etiquetar' && <Etiquetar />}
        </div>
        <footer className="mt-8 border-t border-rule pt-3 text-xs text-ink-3">
          Umbral prioriza la atención editorial y prepara borradores para revisión humana. No publica, no etiqueta noticias como verdaderas o falsas y no sustituye el criterio del equipo.
        </footer>
      </main>
      <AssistantPanel state={assistantState} modal={mobile} closing={assistantClosing} onStateChange={setAssistantState} onClose={closeAssistantPanel} seed={seed} onUnreadChange={onAssistantUnread} />
      <ExportToast toast={toast} anchor={assistantState === 'minimized' ? 'dock' : 'toggle'} onDismiss={dismissToast} />
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
  const [requestedRoute, navigate] = useRoute();
  const [session,setSession] = useState(readSession);
  const [choosingRole,setChoosingRole] = useState(false);
  const route = session && canView(session.role,requestedRoute.view) ? requestedRoute : defaultRoute(session?.role ?? 'editor');
  const go = useCallback((next:Route) => { if(session) navigate(canView(session.role,next.view)?next:defaultRoute(session.role)); },[navigate,session]);
  useEffect(() => { if(session&&!canView(session.role,requestedRoute.view))navigate(defaultRoute(session.role)); },[navigate,requestedRoute.view,session]);
  const [reviewer, setReviewerState] = useState(() => readLocal('umbral.reviewer', readSession()?.labeler ?? ''));
  const [toast, setToast] = useState<AppToast | null>(null);
  const toastSequence = useRef(0);
  const [assistantState, setAssistantState] = useState<AssistantVisibility>('closed');
  const [assistantUnread, setAssistantUnread] = useState(0);
  const [assistantClosing, setAssistantClosing] = useState(false);
  const assistantCloseTimer = useRef<number | undefined>(undefined);
  const [seed, setSeed] = useState({ text: '', topicId: null as string | null, topicTitle: '', n: 0 });

  const openAssistantPanel = useCallback(() => {
    window.clearTimeout(assistantCloseTimer.current);
    assistantCloseTimer.current = undefined;
    setAssistantClosing(false);
    setAssistantState('open');
  }, []);
  const closeAssistantPanel = useCallback(() => {
    window.clearTimeout(assistantCloseTimer.current);
    setAssistantClosing(true);
    assistantCloseTimer.current = window.setTimeout(() => {
      setAssistantState('closed');
      setAssistantClosing(false);
      assistantCloseTimer.current = undefined;
    }, reducedMotion() ? 0 : 120);
  }, []);
  useEffect(() => () => window.clearTimeout(assistantCloseTimer.current), []);

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
  const showToast = useCallback((message: Omit<AppToast, 'id'>) => {
    toastSequence.current += 1;
    setToast({ ...message, id: toastSequence.current });
  }, []);
  const dismissToast = useCallback(() => setToast(null), []);
  const changeRole = useCallback(() => setChoosingRole(true),[]);
  const selectRole = (role:DemoRole) => {
    const next=chooseRole(role,session);setSession(next);setChoosingRole(false);setReviewer(next.labeler);
    navigate(canView(role,requestedRoute.view)?requestedRoute:defaultRoute(role));
  };
  const scopedApi = useMemo(() => boot ? roleApi(boot.api,session,(message,shared) => showToast({tone:shared?'success':'info',title:shared?'Decisión compartida':'Estado de la decisión',description:message})) : null,[boot,session,showToast]);
  const openAssistant = useCallback((prompt?: string, topicId?: string, topicTitle?: string) => {
    openAssistantPanel();
    if (prompt) setSeed((s) => ({ text: prompt, topicId: topicId ?? null, topicTitle: topicTitle ?? '', n: s.n + 1 }));
  }, [openAssistantPanel]);

  const ctx = useMemo(
    () =>
      boot
        ? {
            api: scopedApi!,
            mockReason: boot.reason,
            route,
            go,
            toast,
            showToast,
            dismissToast,
            reviewer,
            setReviewer,
            openAssistant,
            authMode: boot.auth.mode,
            session: session ?? undefined,
            changeRole,
          }
        : null,
    [boot, scopedApi, route, go, toast, showToast, dismissToast, reviewer, setReviewer, openAssistant,session,changeRole],
  );

  if (bootError) return <div className="mx-auto max-w-xl p-6" data-testid="app-boot-error"><ErrorBox error={new Error(bootError)} onRetry={() => setBootAttempt((value) => value + 1)} /></div>;
  if(!session||choosingRole)return <SessionGate onChoose={selectRole} onCancel={session?()=>setChoosingRole(false):undefined} status={!boot?<Loading label={progress?.message ?? 'Conectando con la API…'}/>:undefined}/>;
  if (!ctx) return <div className="mx-auto max-w-xl p-6" data-testid="app-loading"><Loading label={progress?.message ?? "Iniciando Umbral…"} />{progress && <p className="text-sm text-ink-3" aria-live="polite">Intento {progress.attempt} · {Math.floor(progress.elapsedMs / 1000)} s. El primer inicio puede tardar hasta 90 segundos.</p>}</div>;
  return (
    <AppContext.Provider value={ctx}>
      <WarningCenterProvider>
        <Shell assistantState={assistantState} setAssistantState={setAssistantState} assistantClosing={assistantClosing} openAssistantPanel={openAssistantPanel} closeAssistantPanel={closeAssistantPanel} seed={seed} assistantUnread={assistantUnread} onAssistantUnread={setAssistantUnread} />
      </WarningCenterProvider>
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
