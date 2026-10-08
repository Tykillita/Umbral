import { ApiError, HttpApi, type UmbralApi } from './client';
import { BrowserWorkspace, canonicalJson, conflict, parseWorkspace, type WorkspaceCase, type WorkspaceExport } from './workspace';
import type { ArchivedEvidence, ClaudeConnection, ComposeRequestBody, ComposeResponse, PublicContext, QueryRequestBody, PublicDraftResponse, PublicValidationResponse, Authorization, CaseView, Connections, ConnectionStart, Disconnect, DraftEditRequest, DraftProviderChoice, DraftRecord, DraftResponse, ExportResponse, Health, ImpactRequest, Models, QueryResponse, ReviewRequest, Rules, RulesRequest, TopicDetail, TopicFilters, TopicsResponse } from './types';

type Evidence = ArchivedEvidence;
type Validated = PublicValidationResponse;
const now = () => new Date().toISOString();
function fail(message: string): never { throw new ApiError(422, { code: 'validacion', message }); }
const evidence = (detail: TopicDetail): Evidence => ({ articles: detail.articles, officialContext: detail.officialContext, snapshotId: detail.snapshotId, topicId: detail.summary.id, cutoffUtc: detail.cutoffUtc });

export class BrowserWorkspaceApi implements UmbralApi {
  readonly kind = 'live' as const;
  readonly workspaceMode = 'browser' as const;
  private currentHealth: Health | null = null;
  constructor(private readonly remote: HttpApi, readonly workspace = new BrowserWorkspace()) {}
  subscribe = (listener: () => void) => this.workspace.subscribe(listener);
  close = () => this.workspace.close();
  async initialize(): Promise<void> { await Promise.all([this.health(), this.rules()]); }
  async health(): Promise<Health> {
    const health = await this.remote.health();
    this.currentHealth = health;
    return { ...health, persistence: 'IndexedDB en este navegador', authMode: 'public', localMode: false };
  }
  snapshot = () => this.remote.snapshot();
  async rules(): Promise<Rules> {
    const state = await this.workspace.read();
    if (state.rules) return state.rules;
    const rules = await this.remote.rules();
    return this.workspace.change((current) => { current.rules ??= rules; return current.rules; });
  }
  async updateRules(body: RulesRequest): Promise<Rules> {
    const keys = ['R','I','U','N','E'];
    if (!body.author.trim() || body.author.trim().length > 120 || body.reason.trim().length < 3 || body.reason.length > 1000) fail('Indica responsable y motivo (3–1000 caracteres).');
    if (Object.keys(body.weights).length !== 5 || keys.some((key) => !Number.isInteger(body.weights[key]) || body.weights[key]! < 0 || body.weights[key]! > 100) || keys.reduce((sum,key) => sum + body.weights[key]!, 0) !== 100) fail('Los pesos R, I, U, N y E deben ser enteros entre 0 y 100 y sumar 100.');
    await this.rules();
    return this.workspace.change((state) => {
      const previous = state.rules!;
      if (previous.version !== body.expectedVersion) conflict(previous.version, body.expectedVersion);
      const version = previous.version + 1, rulesVersion = 'scoring-v1-editorial-' + version;
      const weights = { ...body.weights };
      state.rules = { ...previous, version, rulesVersion, weights, formula: 'P = ' + keys.map((key) => weights[key] + key).join(' + '),
        history: [...previous.history, { version, rulesVersion, weights, reason: body.reason.trim(), author: body.author.trim(), at: now() }] };
      return state.rules;
    });
  }
  private scoringOverride(c: CaseView) {
    return { topicId: c.topicId, status: c.status, evidenceConfirmed: c.evidenceConfirmed,
      evidenceConfirmedBy: c.evidenceConfirmed === null ? null : 'dispositivo', primarySourceConfirmed: c.primarySourceConfirmed,
      primarySourceConfirmedBy: c.primarySourceConfirmed === null ? null : 'dispositivo',
      primarySourceReason: c.primarySourceConfirmed ? 'Confirmación editorial registrada en el dispositivo.' : null,
      impact: c.impact ? { ...c.impact, author: 'dispositivo', reason: 'Contexto editorial del dispositivo.' } : null };
  }

  private async context(snapshotId?: string): Promise<PublicContext> {
    const [rules, state] = await Promise.all([this.rules(), this.workspace.read()]);
    const health = this.currentHealth ?? (await this.health());
    const selected = snapshotId ?? health.snapshotId;
    return { snapshotId: selected, weights: rules.weights, rulesVersion: rules.rulesVersion,
      topicOverrides: state.cases.filter((entry) => entry.detail.snapshotId === selected).map(({ case: c }) => this.scoringOverride(c)) };
  }
  private async currentRequest<T>(path: string, body: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
    try { return await this.remote.publicRequest<T>(path, { ...body, context: await this.context() }, signal); }
    catch (error) {
      if (!(error instanceof ApiError) || !error.isConflict || !error.details?.currentSnapshotId) throw error;
      await this.health();
      return this.remote.publicRequest<T>(path, { ...body, context: await this.context() }, signal);
    }
  }
  topics = (filters: TopicFilters) => this.currentRequest<TopicsResponse>('/agenda', { filters });
  query = (request: QueryRequestBody, opts: { signal?: AbortSignal } = {}) => this.currentRequest<QueryResponse>('/queries', request, opts.signal);
  compose = (request: ComposeRequestBody, opts: { signal?: AbortSignal } = {}) => this.currentRequest<ComposeResponse>('/queries/compose', request, opts.signal);
  async topic(topicId: string): Promise<TopicDetail> {
    const entry = (await this.workspace.read()).cases.find((item) => item.case.topicId === topicId);
    // Un caso conserva la ficha exacta de su creación, incluso cuando un snapshot sustituye el tema.
        if (entry) {
      try {
      const scored = await this.remote.publicRequest<TopicDetail>('/topics/' + encodeURIComponent(topicId), {
        context: await this.context(entry.detail.snapshotId), evidence: evidence(entry.detail),
      });
      return this.withCase({ ...entry.detail, summary: scored.summary, score: scored.score, rulesVersion: scored.rulesVersion,
        evidence: scored.evidence, impact: scored.impact, recommendedAction: scored.recommendedAction }, entry.case);
      } catch (error) {
        if (!(error instanceof ApiError) || ![0,502,503,504].includes(error.status)) throw error;
        return this.withCase({ ...entry.detail, warnings: [...entry.detail.warnings, 'No se pudo recalcular la ficha. Se conserva el puntaje y la política del corte guardado.'] }, entry.case);
      }
    }
    return this.currentRequest<TopicDetail>('/topics/' + encodeURIComponent(topicId), {});
  }
  private withCase(detail: TopicDetail, c: CaseView): TopicDetail {
    return { ...detail, case: c, impact: c.impact ?? detail.impact,
      summary: { ...detail.summary, reviewStatus: c.status, reviewStatusLabel: c.statusLabel },
      evidence: { ...detail.evidence, reviewerConfirmed: c.evidenceConfirmed, reviewerConfirmedBy: c.evidenceConfirmedBy } };
  }
  private async entry(caseId: string): Promise<WorkspaceCase> {
    const stored = (await this.workspace.read()).cases.find((item) => item.case.caseId === caseId);
    if (stored) return stored;
    if (!caseId.startsWith('case-')) throw new ApiError(404, { code: 'caso_no_encontrado', message: 'No se encontró el caso en este navegador.' });
    const detail = await this.topic(caseId.slice(5));
    return { case: detail.case, detail };
  }
  private async commit(entry: WorkspaceCase, expected: number, candidate: CaseView): Promise<CaseView> {
    const rules = await this.rules();
    return this.workspace.change((state) => {
      const index = state.cases.findIndex((item) => item.case.caseId === entry.case.caseId);
      const currentVersion = index < 0 ? 0 : state.cases[index]!.case.version;
      if (currentVersion !== expected) conflict(currentVersion, expected);
      if (index < 0 && state.cases.length >= 2000) fail('El espacio admite hasta 2000 casos. Exporta una copia para conservar el trabajo antes de abrir otro espacio.');
      const c = { ...candidate, persisted: true, rulesVersion: rules.rulesVersion, history: candidate.history.map((event, index) => index === candidate.history.length - 1 ? { ...event, rulesVersion: rules.rulesVersion } : event) };
      const previous = index < 0 ? entry : state.cases[index]!;
      const impactHistory = previous.impactHistory?.length ? [...previous.impactHistory] : previous.case.impact?.origin === 'editorial' ? [previous.case.impact] : [];
      if (c.impact?.origin === 'editorial' && c.impact.version !== impactHistory.at(-1)?.version) impactHistory.push(c.impact);
      const next = { case: c, detail: this.withCase(entry.detail, c), impactHistory };
      if (index < 0) state.cases.push(next); else state.cases[index] = next;
      return c;
    });
  }
  private changed(c: CaseView, patch: Partial<CaseView>, kind: string, actor: string, comment: string | null = null): CaseView {
    const at = now(), version = c.version + 1;
    const next = { ...c, ...patch, version, persisted: true, createdAt: c.createdAt ?? at, updatedAt: at };
    return { ...next, history: [...c.history, { version, at, kind, actor, comment, fromStatus: kind === 'revision' ? c.status : null,
      toStatus: kind === 'revision' ? next.status : null, draftNumber: next.currentDraft?.number ?? null, rulesVersion: next.rulesVersion }] };
  }
  async createDraft(topicId: string, provider: DraftProviderChoice = 'auto'): Promise<DraftResponse> {
    const detail = await this.topic(topicId);
    const current = await this.health();
    if (detail.snapshotId !== current.snapshotId) fail('Este caso conserva un snapshot anterior. Puedes seguir editándolo y exportándolo con sus fuentes originales.');
    const generated = await this.currentRequest<PublicDraftResponse>('/drafts', { topicId, provider });
    if (generated.evidence.snapshotId !== detail.snapshotId) fail('Este caso conserva un snapshot anterior. Abre un tema del corte vigente para generar un borrador nuevo; puedes seguir editando el archivado.');
    const c = detail.case;
    const draft = { ...generated.draft, draftId: 'd_' + crypto.randomUUID(), number: c.drafts.length + 1 };
    const candidate = this.changed(c, { currentDraft: draft, drafts: [...c.drafts, draft] }, 'generacion_borrador', 'sistema');
    const saved = await this.commit({ case: c, detail }, c.version, candidate);
    return { case: saved, draft, notices: generated.notices };
  }
  async saveDraft(caseId: string, body: DraftEditRequest): Promise<CaseView> {
    const entry = await this.entry(caseId), c = entry.case;
    if (c.version !== body.expectedVersion) conflict(c.version, body.expectedVersion);
    if (!c.currentDraft) fail('El caso no tiene borrador que editar.');
    if (!body.editor.trim() || body.editor.length > 120) fail('La edición exige una persona responsable (máximo 120 caracteres).');
    const pkg = { ...c.currentDraft.package };
    for (const key of ['proposedTitle','brief','publicInterestAngle','researchQuestions','pendingVerifications','script','socialCopy','claims'] as const) {
      if (body[key] !== undefined && body[key] !== null) Object.assign(pkg, { [key]: body[key] });
    }
    const valid = await this.remote.publicRequest<Validated>('/validate', { context: await this.context(entry.detail.snapshotId), topicId: c.topicId, package: pkg, evidence: evidence(entry.detail) });
    if (!valid.package || !valid.validation) fail('El servicio no devolvió el paquete validado.');
    const at = now();
    const draft: DraftRecord = { ...c.currentDraft, draftId: 'd_' + crypto.randomUUID(), number: c.drafts.length + 1, previousDraftId: c.currentDraft.draftId,
      createdAt: at, editedAt: at, editedBy: body.editor.trim(), package: valid.package, validation: valid.validation, rulesVersion: (await this.rules()).rulesVersion };
    return this.commit(entry, body.expectedVersion, this.changed(c, { currentDraft: draft, drafts: [...c.drafts, draft] }, 'edicion_borrador', body.editor.trim(), valid.validation.ok ? 'Edición humana' : 'Edición humana (con errores de validación)'));
  }
  async review(caseId: string, body: ReviewRequest): Promise<CaseView> {
    const entry = await this.entry(caseId);
    if (entry.case.version !== body.expectedVersion) conflict(entry.case.version, body.expectedVersion);
    const c = entry.case;
    const override = this.scoringOverride(c);
    const transientCase: CaseView = { ...c, reviewer: null, evidenceConfirmedBy: override.evidenceConfirmedBy, primarySourceConfirmedBy: override.primarySourceConfirmedBy,
      primarySourceReason: override.primarySourceReason, impact: override.impact, history: [], currentDraft: null,
      drafts: c.currentDraft ? [{ ...c.currentDraft, editedBy: null }] : [] };
    const valid = await this.remote.publicRequest<Validated>('/validate', { context: await this.context(entry.detail.snapshotId), topicId: c.topicId,
      evidence: evidence(entry.detail), case: transientCase, review: body });
    if (!valid.case || valid.case.history.length !== 1 || valid.case.version !== c.version + 1) fail('El servicio no devolvió la revisión validada.');
    const validatedDraft = valid.case.currentDraft;
    const currentDraft = c.currentDraft && validatedDraft ? { ...c.currentDraft, package: validatedDraft.package, validation: validatedDraft.validation } : c.currentDraft;
    const candidate = { ...valid.case, impact: c.impact, primarySourceReason: body.primarySourceConfirmed === null || body.primarySourceConfirmed === undefined ? c.primarySourceReason : valid.case.primarySourceReason,
      evidenceConfirmedBy: body.evidenceConfirmed === null || body.evidenceConfirmed === undefined ? c.evidenceConfirmedBy : valid.case.evidenceConfirmedBy,
      primarySourceConfirmedBy: body.primarySourceConfirmed === null || body.primarySourceConfirmed === undefined ? c.primarySourceConfirmedBy : valid.case.primarySourceConfirmedBy,
      currentDraft, drafts: currentDraft ? [...c.drafts.slice(0, -1), currentDraft] : c.drafts, history: [...c.history, ...valid.case.history] };
    return this.commit(entry, body.expectedVersion, candidate);
  }
  async setImpact(topicId: string, body: ImpactRequest): Promise<CaseView> {
    const detail = await this.topic(topicId), c = detail.case;
    if (c.version !== body.expectedVersion) conflict(c.version, body.expectedVersion);
    if (!body.author.trim() || body.author.length > 120 || body.reason.trim().length < 3 || body.reason.length > 500 || body.justification.trim().length < 20 || body.justification.length > 1500 || !['bajo','medio','alto'].includes(body.level)) fail('El impacto exige responsable, motivo y justificación con contenido.');
    const known = new Set([...detail.articles, ...detail.officialContext.indicators].map((item) => item.id));
    if (!body.evidenceIds.length || body.evidenceIds.some((id) => !known.has(id))) fail('La justificación debe citar evidencia de esta ficha.');
    const impact = { level: body.level, origin: 'editorial', justification: body.justification.trim(), evidenceIds: [...new Set(body.evidenceIds)],
      author: body.author.trim(), reason: body.reason.trim(), at: now(), version: (c.impact?.version ?? 0) + 1 };
    return this.commit({ case: c, detail }, body.expectedVersion, this.changed(c, { impact }, 'impacto', body.author.trim(), body.level + ': ' + body.reason.trim()));
  }
  getCase = async (caseId: string) => (await this.entry(caseId)).case;
  async exportCase(caseId: string): Promise<ExportResponse> {
    const entry = await this.entry(caseId);
    const { exportMarkdown } = await import('./workspaceMarkdown');
    return { caseId, filename: 'umbral-' + entry.case.topicId + '.md', generatedAt: now(), snapshotId: entry.detail.snapshotId, rulesVersion: entry.case.rulesVersion, markdown: exportMarkdown(await this.topic(entry.case.topicId)) };
  }
  async exportWorkspace(): Promise<WorkspaceExport> {
    await this.rules();
    const state = await this.workspace.read();
    return { format: 'umbral-workspace', version: 1, exportedAt: now(), rules: state.rules!, cases: state.cases };
  }
  async importWorkspace(value: unknown): Promise<{ imported: number }> {
    const incoming = parseWorkspace(value);
    return this.workspace.change((state) => {
      let imported = 0;
      for (const entry of incoming.cases) {
        const existing = state.cases.find((item) => item.case.caseId === entry.case.caseId);
        if (existing && canonicalJson(existing) !== canonicalJson(entry)) throw new ApiError(409, { code: 'conflicto_de_importacion', message: 'La copia contiene otra versión de un caso existente. Impórtala en un navegador vacío para conservar ambas.', details: { caseId: entry.case.caseId } });
        if (!existing) { state.cases.push(entry); imported++; }
      }
      if (!state.rules || (state.rules.version === 0 && state.rules.history.length === 0)) state.rules = incoming.rules;
      else if (canonicalJson(state.rules) !== canonicalJson(incoming.rules)) throw new ApiError(409, { code: 'conflicto_de_importacion', message: 'La copia contiene una política de pesos distinta. Impórtala en un navegador vacío.' });
      return { imported };
    });
  }
  async savedCases(): Promise<WorkspaceCase[]> { return (await this.workspace.read()).cases; }
  connections = async (): Promise<Connections> => ({ available: false, profiles: [], activeProfileId: null, reason: 'Las conexiones personales solo se guardan en la aplicación local.' });
  claudeConnection = async (): Promise<ClaudeConnection> => ({ available: false, installed: false, loggedIn: false, loginPending: false, loginCommand: 'claude auth login', account: null, authMethod: null, reason: 'Las conexiones personales solo se guardan en la aplicación local.' });
  private unavailable(): never { throw new ApiError(403, { code: 'solo_localhost', message: 'Esta conexión está disponible en la aplicación local.' }); }
  startConnection = async (_body: ConnectionStart): Promise<Authorization> => this.unavailable();
  selectConnection = async (_profileId: string): Promise<Connections> => this.unavailable();
  connectionModels = async (): Promise<Models> => this.unavailable();
  selectConnectionModel = async (_model: string): Promise<Models> => this.unavailable();
  disconnect = async (_profileId: string): Promise<Disconnect> => this.unavailable();
  startClaudeLogin = async (): Promise<ClaudeConnection> => this.unavailable();
  claudeLogout = async (): Promise<ClaudeConnection> => this.unavailable();
}
