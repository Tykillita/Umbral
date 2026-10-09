import type { WorkspaceCase, WorkspaceExport } from './workspace';
import type {} from '../desktop';
import { getConnectorAuthToken } from '../auth';
import type {
  CaseView,
  DraftEditRequest,
  DraftProviderChoice,
  DraftResponse,
  ErrorBody,
  ExportResponse,
  Health,
  ImpactRequest,
  ComposeResponse,
  ComposeRequestBody,
  QueryRequestBody,
  QueryResponse,
  ReviewRequest,
  Rules,
  RulesRequest,
  Connections,
  ConnectionStart,
  Authorization,
  Models,
  Disconnect,
  ClaudeConnection,
  SnapshotInfo,
  TopicDetail,
  NotionExportResponse,
  NotionStatusResponse,
  ConnectorProvider,
  ConnectorAuthorization,
  ConnectorOverview,
  ConnectorPage,
  ConnectorChannel,
  SlackNotificationPreferences,
  SlackNotificationResult,
  SlackShareRequest,
  TopicFilters,
  TopicsResponse,
  PublicAlertFeed,
} from './types';

export interface BootProgress { attempt: number; elapsedMs: number; message: string }

/** Contrato de acceso a datos. Lo implementan el cliente HTTP real y el mock etiquetado. */
export interface UmbralApi {
  readonly kind: 'live' | 'mock';
  readonly workspaceMode?: 'browser';
  subscribe?(listener: () => void): () => void;
  close?(): Promise<void>;
  exportWorkspace?(): Promise<WorkspaceExport>;
  importWorkspace?(value: unknown): Promise<{ imported: number }>;
  savedCases?(): Promise<WorkspaceCase[]>;
  health(): Promise<Health>;
  rules(): Promise<Rules>;
  updateRules(body: RulesRequest): Promise<Rules>;
  connections(): Promise<Connections>;
  startConnection(body: ConnectionStart): Promise<Authorization>;
  selectConnection(profileId: string): Promise<Connections>;
  connectionModels(): Promise<Models>;
  selectConnectionModel(model: string): Promise<Models>;
  disconnect(profileId: string): Promise<Disconnect>;
  claudeConnection(): Promise<ClaudeConnection>;
  startClaudeLogin(): Promise<ClaudeConnection>;
  claudeLogout(): Promise<ClaudeConnection>;
  snapshot(): Promise<SnapshotInfo>;
  alerts(): Promise<PublicAlertFeed>;
  topics(filters: TopicFilters): Promise<TopicsResponse>;
  topic(topicId: string): Promise<TopicDetail>;
  query(req: QueryRequestBody, opts?: { signal?: AbortSignal }): Promise<QueryResponse>;
  /** Redacción opcional con IA de la respuesta con fuentes; ante cualquier fallo devuelve la de reglas. */
  compose(req: ComposeRequestBody, opts?: { signal?: AbortSignal }): Promise<ComposeResponse>;
  createDraft(topicId: string, provider?: DraftProviderChoice): Promise<DraftResponse>;
  saveDraft(caseId: string, body: DraftEditRequest): Promise<CaseView>;
  review(caseId: string, body: ReviewRequest): Promise<CaseView>;
  setImpact(topicId: string, body: ImpactRequest): Promise<CaseView>;
  getCase(caseId: string): Promise<CaseView>;
  exportCase(caseId: string): Promise<ExportResponse>;
  notionStatus?(): Promise<NotionStatusResponse>;
  exportCaseToNotion?(caseId: string): Promise<NotionExportResponse>;
  connectorOverview?(): Promise<ConnectorOverview>;
  startConnector?(provider: ConnectorProvider): Promise<ConnectorAuthorization>;
  disconnectConnector?(provider: ConnectorProvider): Promise<void>;
  notionPages?(): Promise<ConnectorPage[]>;
  chooseNotionDestination?(pageId: string): Promise<void>;
  exportMarkdownToNotion?(markdown: string): Promise<NotionExportResponse>;
  slackChannels?(): Promise<ConnectorChannel[]>;
  chooseSlackChannel?(channelId: string): Promise<void>;
  slackNotificationPreferences?(): Promise<SlackNotificationPreferences>;
  saveSlackNotificationPreferences?(value: SlackNotificationPreferences): Promise<void>;
  shareCaseToSlack?(value: SlackShareRequest): Promise<SlackNotificationResult>;
  notifySlackReview?(value: SlackShareRequest): Promise<SlackNotificationResult>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;
  readonly retryAfter: number | null;

  constructor(status: number, body: Partial<ErrorBody> | null, message?: string, retryAfter: number | null = null) {
    super(body?.message ?? message ?? `Error HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = body?.code ?? (status === 0 ? 'sin_conexion' : 'error_http');
    this.details = (body?.details as Record<string, unknown> | null | undefined) ?? null;
    this.retryAfter = retryAfter;
  }

  get isConflict(): boolean {
    return this.status === 409;
  }
  get currentVersion(): number | null {
    const v = this.details?.currentVersion;
    return typeof v === 'number' ? v : null;
  }
}

export function describeError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 0 && e.code.startsWith('almacenamiento_')) return e.message;
    if (e.status === 0) return 'No se pudo contactar con la API. Revisa la conexión o que el backend esté en marcha.';
    if (e.status === 429) return `Límite de consultas alcanzado.${e.retryAfter ? ` Reintenta en ${e.retryAfter} s.` : ''}`;
    if (e.status === 503) return `Servicio no disponible: ${e.message}`;
    return e.message;
  }
  return e instanceof Error ? e.message : 'Error desconocido';
}

type TokenGetter = () => Promise<string | null>;

export class HttpApi implements UmbralApi {
  readonly kind = 'live' as const;
  constructor(
    private readonly baseUrl: string,
    private readonly getToken: TokenGetter,
  ) {}

  private url(path: string, params?: Record<string, string | number | boolean | undefined | null>): string {
    const base = this.baseUrl.replace(/\/+$/, '');
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params ?? {})) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
    }
    const s = qs.toString();
    return `${base}/api/v1${path}${s ? `?${s}` : ''}`;
  }

  private async request<T>(
    method: string,
    path: string,
    opts: { params?: Record<string, string | number | boolean | undefined | null>; body?: unknown; timeoutMs?: number; signal?: AbortSignal; connectorAuth?: boolean } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    const desktopToken = typeof window !== 'undefined' ? window.umbralDesktop?.apiToken : null;
    const destination = typeof window !== 'undefined' ? new URL(this.url(path, opts.params), window.location.origin) : null;
    if (desktopToken && destination?.origin === window.location.origin && ['localhost','127.0.0.1','[::1]','::1'].includes(destination.hostname)) headers['x-umbral-desktop-token'] = desktopToken;
    const token = opts.connectorAuth ? await getConnectorAuthToken() : await this.getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 60_000);
    const abort = () => ctrl.abort();
    opts.signal?.addEventListener('abort', abort, { once: true });
    if (opts.signal?.aborted) ctrl.abort();
    try {
      let res: Response;
      try {
        if (opts.connectorAuth && typeof window !== 'undefined' && window.umbralDesktop?.requestConnector) {
          if (!token) throw new ApiError(401, { code: 'identidad_requerida', message: 'Se requiere una identidad anónima para conectar servicios.' });
          const response = await window.umbralDesktop.requestConnector({
            path,
            method: method as 'GET' | 'POST' | 'PUT' | 'DELETE',
            body: opts.body,
            token,
          });
          res = new Response(JSON.stringify(response.body ?? null), {
            status: response.status,
            headers: { 'Content-Type': 'application/json', ...(response.retryAfter ? { 'Retry-After': response.retryAfter } : {}) },
          });
        } else {
          res = await fetch(this.url(path, opts.params), {
            method,
            redirect: 'error',
            headers,
            body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
            signal: ctrl.signal,
          });
        }
      } catch (error) {
        if (error instanceof ApiError) throw error;
        throw new ApiError(0, null, 'No se pudo contactar con la API');
      }
      const contentType = res.headers.get('Content-Type') ?? '';
      if (res.ok && !/application\/(?:[a-z0-9.+-]*\+)?json/i.test(contentType)) {
        throw new ApiError(res.status, { code: 'respuesta_no_json', message: 'La dirección de la API devolvió una página en lugar de JSON. Revisa PUBLIC_API_URL y la ruta del servicio.' });
      }
  
      if (!res.ok) {
        let body: Partial<ErrorBody> | null = null;
        try {
          const j = (await res.json()) as unknown;
          if (j && typeof j === 'object') {
            const o = j as Record<string, unknown>;
            if (typeof o.code === 'string') body = o as Partial<ErrorBody>;
            else if (Array.isArray(o.detail)) {
              // Errores 422 estándar de FastAPI.
              const first = o.detail[0] as { msg?: string; loc?: unknown[] } | undefined;
              body = { code: 'validacion', message: first?.msg ? `${first.msg} (${(first.loc ?? []).join('.')})` : 'Entrada no válida', details: null };
            }
          }
        } catch {
          /* cuerpo no JSON */
        }
        const ra = Number(res.headers.get('Retry-After'));
        throw new ApiError(res.status, body, undefined, Number.isFinite(ra) && ra > 0 ? ra : null);
      }
      try { return (await res.json()) as T; } catch { throw new ApiError(res.status, { code: 'json_invalido', message: 'La API devolvió JSON incompleto o inválido. Reintenta la conexión.' }); }
      } finally { clearTimeout(timer); opts.signal?.removeEventListener('abort', abort); }
  }

  publicRequest = <T>(path: string, body: unknown, signal?: AbortSignal) => this.request<T>('POST', '/public' + path, { body, timeoutMs: path === '/drafts' || path === '/queries/compose' ? 120_000 : 60_000, signal });
  async waitUntilReady(onProgress?: (progress: BootProgress) => void, signal?: AbortSignal, budgetMs = 90_000): Promise<Health> {
    const started = Date.now();
    let attempt = 0;
    while (Date.now() - started < budgetMs) {
      if (signal?.aborted) throw new DOMException('Arranque cancelado', 'AbortError');
      attempt++;
      onProgress?.({ attempt, elapsedMs: Date.now() - started, message: attempt === 1 ? 'Conectando con Umbral…' : 'El servicio está iniciando. Seguimos intentando la conexión…' });
      try { return await this.request<Health>('GET', '/health', { timeoutMs: Math.min(10_000, budgetMs - (Date.now() - started)), signal }); }
      catch (error) {
        if (signal?.aborted) throw new DOMException('Arranque cancelado', 'AbortError');
        if (!(error instanceof ApiError) || ![0, 502, 503, 504].includes(error.status) || error.code === 'respuesta_no_json') throw error;
        const remaining = budgetMs - (Date.now() - started);
        if (remaining <= 0) throw error;
        await new Promise<void>((resolve, reject) => {
          const cancelled = () => { clearTimeout(timer); reject(new DOMException('Arranque cancelado', 'AbortError')); };
          const timer = setTimeout(() => { signal?.removeEventListener('abort', cancelled); resolve(); }, Math.min(3000, remaining));
          signal?.addEventListener('abort', cancelled, { once: true });
        });
      }
    }
    throw new ApiError(503, { code: 'inicio_agotado', message: 'El servicio no respondió tras 90 segundos. Tu trabajo guardado permanece en este dispositivo. Reintenta la conexión.' });
  }

  health = () => this.request<Health>('GET', '/health', { timeoutMs: 4000 });
  rules = () => this.request<Rules>('GET', '/rules');
  updateRules = (body: RulesRequest) => this.request<Rules>('PUT', '/rules', { body });
  connections = () => this.request<Connections>('GET', '/connections/chatgpt');
  startConnection = (body: ConnectionStart) => this.request<Authorization>('POST', '/connections/chatgpt/start', { body });
  selectConnection = (profileId: string) => this.request<Connections>('POST', '/connections/chatgpt/select', { body: { profileId } });
  connectionModels = () => this.request<Models>('GET', '/connections/chatgpt/models');
  selectConnectionModel = (model: string) => this.request<Models>('PUT', '/connections/chatgpt/model', { body: { model } });
  disconnect = (profileId: string) => this.request<Disconnect>('DELETE', `/connections/chatgpt/${encodeURIComponent(profileId)}`);
  claudeConnection = () => this.request<ClaudeConnection>('GET', '/connections/claude');
  startClaudeLogin = () => this.request<ClaudeConnection>('POST', '/connections/claude/login');
  claudeLogout = () => this.request<ClaudeConnection>('POST', '/connections/claude/logout');
  snapshot = () => this.request<SnapshotInfo>('GET', '/snapshot');
  alerts = () => this.request<PublicAlertFeed>('GET', '/public/alerts');
  topics = (f: TopicFilters) =>
    this.request<TopicsResponse>('GET', '/topics', {
      params: {
        limit: f.limit ?? 5,
        scope: f.scope ?? 'in_scope',
        category: f.category,
        evidence: f.evidence,
        band: f.band,
        reviewStatus: f.reviewStatus,
        q: f.q?.trim(),
        includeComponents: true,
        tvnGap: f.tvnGap || undefined,
      },
    });
  topic = (id: string) => this.request<TopicDetail>('GET', `/topics/${encodeURIComponent(id)}`);
  query = (req: QueryRequestBody, opts: { signal?: AbortSignal } = {}) =>
    this.request<QueryResponse>('POST', '/queries', { body: req, signal: opts.signal });
  compose = (req: ComposeRequestBody, opts: { signal?: AbortSignal } = {}) =>
    this.request<ComposeResponse>('POST', '/queries/compose', { body: req, signal: opts.signal, timeoutMs: 120_000 });
  createDraft = (topicId: string, provider: DraftProviderChoice = 'auto') =>
    this.request<DraftResponse>('POST', `/topics/${encodeURIComponent(topicId)}/drafts`, {
      body: { provider },
      timeoutMs: 120_000,
    });
  saveDraft = (caseId: string, body: DraftEditRequest) =>
    this.request<CaseView>('PUT', `/cases/${encodeURIComponent(caseId)}/draft`, { body });
  review = (caseId: string, body: ReviewRequest) =>
    this.request<CaseView>('PATCH', `/cases/${encodeURIComponent(caseId)}/review`, { body });
  setImpact = (topicId: string, body: ImpactRequest) =>
    this.request<CaseView>('PUT', `/topics/${encodeURIComponent(topicId)}/impact`, { body });
  getCase = (caseId: string) => this.request<CaseView>('GET', `/cases/${encodeURIComponent(caseId)}`);
  exportWorkspace = () => this.request<WorkspaceExport>('GET', '/workspace/export');
  importWorkspace = (value: unknown) => this.request<{ imported: number }>('POST', '/workspace/import', { body: value });
  savedCases = async () => (await this.exportWorkspace()).cases;
  exportCase = (caseId: string) => this.request<ExportResponse>('GET', `/cases/${encodeURIComponent(caseId)}/export`);
  notionStatus = () => this.request<NotionStatusResponse>('GET', '/notion/status');
  exportCaseToNotion = (caseId: string) => this.request<NotionExportResponse>('POST', `/cases/${encodeURIComponent(caseId)}/export/notion`);
  connectorOverview = () => this.request<ConnectorOverview>('GET', '/connectors', { connectorAuth: true });
  startConnector = (provider: ConnectorProvider) => this.request<ConnectorAuthorization>('POST', `/connectors/${provider}/start`, { connectorAuth: true });
  disconnectConnector = async (provider: ConnectorProvider) => { await this.request<{ disconnected: boolean }>('DELETE', `/connectors/${provider}`, { connectorAuth: true }); };
  notionPages = async () => (await this.request<{ items: ConnectorPage[] }>('GET', '/connectors/notion/pages', { connectorAuth: true })).items;
  chooseNotionDestination = async (pageId: string) => { await this.request<{ saved: boolean }>('PUT', '/connectors/notion/destination', { body: { pageId }, connectorAuth: true }); };
  exportMarkdownToNotion = (markdown: string) => this.request<NotionExportResponse>('POST', '/connectors/notion/export', { body: { markdown }, connectorAuth: true, timeoutMs: 30_000 });
  slackChannels = async () => (await this.request<{ items: ConnectorChannel[] }>('GET', '/connectors/slack/channels', { connectorAuth: true })).items;
  chooseSlackChannel = async (channelId: string) => { await this.request<{ saved: boolean }>('PUT', '/connectors/slack/channel', { body: { channelId }, connectorAuth: true }); };
  slackNotificationPreferences = () => this.request<SlackNotificationPreferences>('GET', '/connectors/slack/notifications', { connectorAuth: true });
  saveSlackNotificationPreferences = async (value: SlackNotificationPreferences) => { await this.request<{ saved: boolean }>('PUT', '/connectors/slack/notifications', { body: value, connectorAuth: true }); };
  shareCaseToSlack = (value: SlackShareRequest) => this.request<SlackNotificationResult>('POST', '/connectors/slack/share', { body: value, connectorAuth: true, timeoutMs: 20_000 });
  notifySlackReview = (value: SlackShareRequest) => this.request<SlackNotificationResult>('POST', '/connectors/slack/review-event', { body: value, connectorAuth: true, timeoutMs: 20_000 });
}
