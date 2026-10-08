import type { CaseView, ImpactAssignment, Rules, TopicDetail } from './types';
import { ApiError } from './client';

export interface WorkspaceCase { case: CaseView; detail: TopicDetail; impactHistory?: ImpactAssignment[] }
export interface WorkspaceExport { format: 'umbral-workspace'; version: 1; exportedAt: string; rules: Rules; cases: WorkspaceCase[] }
export interface WorkspaceState { rules: Rules | null; cases: WorkspaceCase[] }
const empty = (): WorkspaceState => ({ rules: null, cases: [] });
const copy = <T>(value: T): T => structuredClone(value);
export const WORKSPACE_DB = 'umbral-workspace-v1';
export const WORKSPACE_CHANNEL = 'umbral-workspace-v1';

function storageError(error?: unknown): ApiError {
  const quota = error instanceof DOMException && error.name === 'QuotaExceededError';
  return new ApiError(0, { code: quota ? 'almacenamiento_lleno' : 'almacenamiento_no_disponible',
    message: quota ? 'El almacenamiento de este navegador está lleno. Exporta una copia y libera espacio; el cambio no se guardó.'
      : 'Este navegador no permite guardar el espacio de trabajo. Habilita el almacenamiento y reintenta; el cambio no se guardó.' });
}

/** Cada modificación se decide dentro de una única transacción readwrite: CAS también entre pestañas. */
export class BrowserWorkspace {
  private database: Promise<IDBDatabase> | null = null;
  private channel: BroadcastChannel | null = null;
  private listeners = new Set<() => void>();
  constructor(private readonly factory: IDBFactory | undefined = globalThis.indexedDB, private readonly name = WORKSPACE_DB) {
    if (typeof BroadcastChannel !== 'undefined') {
      this.channel = new BroadcastChannel(name);
      this.channel.onmessage = () => this.listeners.forEach((listener) => listener());
    }
  }
  subscribe(listener: () => void): () => void { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; }
  private open(): Promise<IDBDatabase> {
    if (!this.factory) return Promise.reject(storageError());
    if (!this.database) this.database = new Promise<IDBDatabase>((resolve, reject) => {
      const request = this.factory!.open(this.name, 1);
      request.onupgradeneeded = () => request.result.createObjectStore('workspace');
      request.onsuccess = () => { request.result.onversionchange = () => { request.result.close(); this.database = null; }; resolve(request.result); };
      request.onerror = () => reject(storageError(request.error));
      request.onblocked = () => reject(storageError());
    }).catch((error: unknown) => { this.database = null; throw error instanceof ApiError ? error : storageError(error); });
    return this.database!;
  }
  async read(): Promise<WorkspaceState> {
    const database = await this.open();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction('workspace', 'readonly');
      const request = transaction.objectStore('workspace').get('current');
      request.onsuccess = () => resolve(copy((request.result as WorkspaceState | undefined) ?? empty()));
      request.onerror = () => reject(storageError(request.error));
    });
  }
  async change<T>(update: (state: WorkspaceState) => T): Promise<T> {
    const database = await this.open();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction('workspace', 'readwrite');
      const store = transaction.objectStore('workspace');
      const request = store.get('current');
      let result: T;
      let failure: unknown;
      request.onsuccess = () => {
        try {
          const state = (request.result as WorkspaceState | undefined) ?? empty();
          result = update(state);
          store.put(state, 'current');
        } catch (error) { failure = error; transaction.abort(); }
      };
      transaction.oncomplete = () => { this.channel?.postMessage({ changed: true }); this.listeners.forEach((listener) => listener()); resolve(copy(result)); };
      transaction.onabort = () => reject(failure instanceof ApiError ? failure : storageError(failure ?? transaction.error));
      transaction.onerror = () => { /* onabort reports the transaction failure. */ };
    });
  }
  async close(): Promise<void> { (await this.database)?.close(); this.database = null; this.channel?.close(); this.listeners.clear(); }
}

function invalid(message: string): never { throw new ApiError(422, { code: 'copia_invalida', message: 'Copia no válida: ' + message }); }
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string';
const integer = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const statuses = new Set(['nuevo', 'en_revision', 'requiere_evidencia', 'aprobado_como_borrador', 'descartado']);

export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  if (record(value)) return '{' + Object.keys(value).filter((key) => value[key] !== undefined).sort().map((key) => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
function validUrl(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (!text(value)) return false;
  try { const url = new URL(value); return ['https:','http:'].includes(url.protocol) && !url.username && !url.password; } catch { return false; }
}
function validClaims(value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  const ids = new Set<string>();
  return value.every((claim) => {
    if (!record(claim) || !text(claim.id) || ids.has(claim.id) || !text(claim.text) || !['hecho','declaracion','inferencia','hipotesis'].includes(String(claim.type)) || !Array.isArray(claim.citations)) return false;
    ids.add(claim.id);
    return claim.citations.every((citation: unknown) => record(citation) && text(citation.evidenceId) && text(citation.field) && (citation.passage === null || citation.passage === undefined || text(citation.passage)));
  });
}
function validWeights(value: unknown): boolean {
  if (!record(value)) return false;
  const keys = ['R','I','U','N','E'];
  return Object.keys(value).length === 5 && keys.every((key) => integer(value[key]) && Number(value[key]) <= 100) && keys.reduce((sum,key) => sum + Number(value[key]), 0) === 100;
}

function validateDetail(value: Record<string, unknown>): void {
  const s = value.summary, ev = value.evidence, score = value.score, official = value.officialContext;
  if (!record(s) || !['economia','logistica_canal','turismo','servicios_publicos','eventos_naturales','regulacion','indeterminado'].includes(String(s.category)) ||
      !['bajo','medio','alto'].includes(String(s.band)) || !['insuficiente','parcial','suficiente'].includes(String(s.evidenceStatus)) || !statuses.has(String(s.reviewStatus)) ||
      !text(s.title) || !text(s.categoryLabel) || !finite(s.score) || !integer(s.articleCount)) invalid('resumen del tema incompleto.');
  if (!['fixture','provisional','congelado'].includes(String(value.dataMode)) || !text(value.whatIsReported) || !text(value.recommendedAction) || !strings(value.warnings) || !strings(value.pendingVerifications) || !validClaims(value.supportedClaims)) invalid('campos de la ficha incorrectos.');
  if (!Array.isArray(value.articles) || !value.articles.length || value.articles.length > 1000 || value.articles.some((a) => !record(a) || ['id','title','url','outlet','origin','originKey'].some((key) => !text(a[key])) || !validUrl(a.url))) invalid('artículos incompletos o URL no válida.');
  if (!record(official) || !Array.isArray(official.indicators) || !strings(official.limitations) || !text(official.relationRationale) || official.indicators.some((p) => !record(p) || ['id','countryIso3','indicatorName','indicatorId'].some((key) => !text(p[key])) || !integer(p.year) || (p.value !== null && !finite(p.value)) || !validUrl(p.sourceUrl))) invalid('contexto oficial incompleto.');
  if (!record(ev) || !['insuficiente','parcial','suficiente'].includes(String(ev.status)) || !text(ev.rationale) || !text(ev.statusLabel) || !Array.isArray(ev.gaps) || ev.gaps.some((g) => !record(g) || !text(g.code) || !text(g.message))) invalid('estado de evidencia incompleto.');
  if (!record(score) || !finite(score.total) || !Array.isArray(score.components) || score.components.some((p) => !record(p) || ['key','label','rule','justification'].some((key) => !text(p[key])) || !strings(p.limits) || !strings(p.evidenceIds) || !finite(p.weight) || !finite(p.value) || !finite(p.points))) invalid('puntuación incompleta.');
  if (!Array.isArray(value.reporters) || value.reporters.some((r) => !record(r) || !text(r.outlet) || !text(r.origin) || !text(r.role) || !strings(r.evidenceIds))) invalid('procedencias incompletas.');
  if (!Array.isArray(value.contradictions) || value.contradictions.some((ct) => !record(ct) || !text(ct.id) || !text(ct.description) || !text(ct.pendingVerification) || !Array.isArray(ct.versions) || ct.versions.some((v: unknown) => !record(v) || !text(v.evidenceId) || !text(v.statement) || !text(v.outlet)))) invalid('contradicciones incompletas.');
  const impact = value.impact;
  if (!record(impact) || !['bajo','medio','alto'].includes(String(impact.level)) || !text(impact.justification) || !text(impact.origin) || !strings(impact.evidenceIds)) invalid('impacto incompleto.');
}


/** El formato es común a navegador y escritorio; se valida antes de abrir la transacción de importación. */
export function parseWorkspace(value: unknown): WorkspaceExport {
  if (!record(value) || value.format !== 'umbral-workspace' || value.version !== 1 || !text(value.exportedAt) || !Number.isFinite(Date.parse(value.exportedAt))) invalid('formato o versión desconocidos.');
  if (!record(value.rules) || !record(value.rules.weights) || !integer(value.rules.version) || !text(value.rules.rulesVersion) || !Array.isArray(value.rules.history)) invalid('faltan las reglas y su historial.');
  const keys = ['R', 'I', 'U', 'N', 'E'];
  const weights = value.rules.weights;
  if (Object.keys(weights).length !== 5 || keys.some((key) => !integer(weights[key]) || Number(weights[key]) > 100) || keys.reduce((sum, key) => sum + Number(weights[key]), 0) !== 100) invalid('los pesos deben sumar 100.');
  if (!text(value.rules.formula) || !record(value.rules.bands) || !record(value.rules.rules) || !Array.isArray(value.rules.changelog)) invalid('política incompleta.');
  if (value.rules.history.length !== value.rules.version || value.rules.history.some((revision, index) => !record(revision) || revision.version !== index + 1 || !text(revision.rulesVersion) || !validWeights(revision.weights) || !text(revision.author) || !revision.author.trim() || revision.author.length > 120 || !text(revision.reason) || revision.reason.trim().length < 3 || revision.reason.length > 1000 || !text(revision.at))) invalid('historial de pesos discontinuo o incorrecto.');
  const lastRules = value.rules.history.at(-1);
  if (lastRules && (!record(lastRules) || lastRules.rulesVersion !== value.rules.rulesVersion || canonicalJson(lastRules.weights) !== canonicalJson(weights))) invalid('la política vigente no coincide con su historial.');
  if (!lastRules && canonicalJson(weights) !== canonicalJson({ R: 30, I: 25, U: 20, N: 15, E: 10 })) invalid('los pesos modificados necesitan historial.');

  if (!Array.isArray(value.cases) || value.cases.length > 2000) invalid('lista de casos demasiado grande o ausente.');
  const ids = new Set<string>();
  for (const entry of value.cases) {
    if (!record(entry) || !record(entry.case) || !record(entry.detail)) invalid('caso o evidencia ausentes.');
    const c = entry.case, d = entry.detail; validateDetail(d);
    if (!text(c.caseId) || !c.caseId.startsWith('case-') || !text(c.topicId) || c.caseId !== 'case-' + c.topicId || !text(c.snapshotId) || !text(c.rulesVersion) || !integer(c.version) || !statuses.has(String(c.status)) || !text(c.statusLabel)) invalid('identidad, versión o estado de caso incorrectos.');
    if (ids.has(c.caseId)) invalid('hay casos repetidos.');
    ids.add(c.caseId);
    if (!Array.isArray(c.drafts) || !Array.isArray(c.history) || !Array.isArray(c.allowedTransitions) || !record(d.summary) || d.summary.id !== c.topicId || d.snapshotId !== c.snapshotId || !Array.isArray(d.articles) || !record(d.officialContext) || !Array.isArray(d.officialContext.indicators)) invalid('la ficha no corresponde al caso.');
    if (!record(d.case) || d.case.caseId !== c.caseId || !record(d.score) || !Array.isArray(d.score.components) || !record(d.evidence) || !record(d.impact) || !Array.isArray(d.reporters) || !Array.isArray(d.supportedClaims) || !Array.isArray(d.pendingVerifications) || !Array.isArray(d.contradictions) || !Array.isArray(d.warnings)) invalid('ficha incompleta.');
    if (c.history.length !== c.version || c.history.some((event, index) => !record(event) || event.version !== index + 1 || !text(event.at) || !text(event.actor) || !text(event.kind))) invalid('historial de caso discontinuo.');
    const impactHistory = entry.impactHistory;
    if (impactHistory !== undefined) {
      if (!Array.isArray(impactHistory)) invalid('historial de impacto incorrecto.');
      const known = new Set([...d.articles, ...d.officialContext.indicators].map((item) => record(item) ? item.id : null));
      const firstVersion = record(impactHistory[0]) ? impactHistory[0].version : 0;
      if (impactHistory.some((impact, index) => !record(impact) || !integer(impact.version) || impact.version < 1 || impact.version !== Number(firstVersion) + index || impact.origin !== 'editorial' || !['bajo','medio','alto'].includes(String(impact.level)) || !text(impact.justification) || impact.justification.trim().length < 20 || !text(impact.reason) || impact.reason.trim().length < 3 || !text(impact.author) || !impact.author.trim() || !strings(impact.evidenceIds) || !impact.evidenceIds.length || impact.evidenceIds.some((id) => !known.has(id)))) invalid('historial de impacto discontinuo o sin evidencia del tema.');
      if (impactHistory.length && canonicalJson(impactHistory.at(-1)) !== canonicalJson(c.impact)) invalid('el impacto vigente no coincide con su historial.');
    }
    const draftIds = new Set<string>();
    for (const [index, draft] of c.drafts.entries()) {
      if (!record(draft) || !text(draft.draftId) || draftIds.has(draft.draftId) || draft.number !== index + 1 || !record(draft.package) || !record(draft.validation) || typeof draft.validation.ok !== 'boolean' || !Array.isArray(draft.validation.issues)) invalid('versiones de borrador incorrectas.');
      if (!strings(draft.validation.rejectedClaimIds) || !record(draft.validation.wordCounts) || !finite(draft.validation.scriptSecondsEstimate) || !finite(draft.validation.citationCoverage) || !text(draft.validation.note) || draft.validation.issues.some((issue) => !record(issue) || !text(issue.code) || !text(issue.message) || !['error','warning'].includes(String(issue.severity)))) invalid('informe de validación incompleto.');
      draftIds.add(draft.draftId);
      const pkg = draft.package;
      if (['proposedTitle','brief','publicInterestAngle','script','socialCopy'].some((key) => !text(pkg[key])) || !Array.isArray(pkg.claims) || !strings(pkg.researchQuestions) || !strings(pkg.pendingVerifications) || !strings(pkg.limitations)) invalid('paquete editorial incompleto.');
      if (!validClaims(pkg.claims)) invalid('afirmaciones o citas incorrectas.');
    }
    const last = c.drafts.at(-1);
    if ((last && (!record(c.currentDraft) || c.currentDraft.draftId !== last.draftId || canonicalJson(c.currentDraft) !== canonicalJson(last))) || (!last && c.currentDraft !== null)) invalid('borrador vigente inconsistente.');
    if (c.version === 0 || c.persisted !== true) invalid('la copia solo debe contener casos guardados.');
  }
  const parsed = copy(value as unknown as WorkspaceExport);
  for (const entry of parsed.cases) entry.impactHistory = entry.impactHistory?.length ? entry.impactHistory : entry.case.impact?.origin === 'editorial' ? [entry.case.impact] : [];
  return parsed;
}

export function conflict(currentVersion: number, expectedVersion: number): never {
  throw new ApiError(409, { code: 'conflicto_de_version', message: 'Otra pestaña cambió el caso. Recarga la versión vigente antes de guardar.', details: { currentVersion, expectedVersion } });
}
