// API simulada EN EL NAVEGADOR con datos de demostración. Implementa la misma interfaz que HttpApi,
// incluida la versión optimista (409) y las transiciones de revisión, para poder recorrer la UI sin backend.
// La interfaz siempre muestra el banner «mock-banner» cuando se usa este módulo.
import { ApiError, type UmbralApi } from '../api/client';
import type {
  CaseView,
  Claim,
  DraftEditRequest,
  DraftProviderChoice,
  DraftRecord,
  Rules,
  RulesRequest,
  Connections,
  ConnectionStart,
  Authorization,
  Models,
  Disconnect,
  DraftResponse,
  ExportResponse,
  ImpactRequest,
  ComposeResponse,
  QueryRequestBody,
  QueryResponse,
  ReviewRequest,
  ReviewStatus,
  TopicDetail,
  TopicFilters,
  TopicsResponse,
  TopicSummary,
} from '../api/types';
import {
  MOCK_CUTOFF,
  MOCK_HEALTH,
  MOCK_RULES,
  MOCK_RULES_VERSION,
  MOCK_SNAPSHOT,
  MOCK_SNAPSHOT_ID,
  MOCK_SPECS,
  buildDetail,
} from './data';

const STATUS_LABEL: Record<ReviewStatus, string> = {
  nuevo: 'Nuevo',
  en_revision: 'En revisión',
  requiere_evidencia: 'Requiere evidencia',
  aprobado_como_borrador: 'Aprobado como borrador',
  descartado: 'Descartado',
};

const TRANSITIONS: Record<ReviewStatus, ReviewStatus[]> = {
  nuevo: ['en_revision'],
  en_revision: ['requiere_evidencia', 'aprobado_como_borrador', 'descartado'],
  requiere_evidencia: ['en_revision', 'descartado'],
  aprobado_como_borrador: ['en_revision'],
  descartado: ['en_revision'],
};

const delay = (ms = 120) => new Promise((r) => setTimeout(r, ms));
const now = () => new Date().toISOString();
const words = (s: string) => s.trim().split(/\s+/).filter(Boolean).length;

function blankCase(topicId: string): CaseView {
  return {
    caseId: `case-${topicId}`,
    topicId,
    snapshotId: MOCK_SNAPSHOT_ID,
    rulesVersion: MOCK_RULES_VERSION,
    persisted: false,
    version: 0,
    status: 'nuevo',
    statusLabel: STATUS_LABEL.nuevo,
    allowedTransitions: TRANSITIONS.nuevo,
    reviewer: null,
    evidenceConfirmed: null,
    evidenceConfirmedBy: null,
    primarySourceConfirmed: null,
    primarySourceConfirmedBy: null,
    primarySourceReason: null,
    currentDraft: null,
    drafts: [],
    history: [],
    impact: null,
    createdAt: null,
    updatedAt: null,
  };
}

export class MockApi implements UmbralApi {
  readonly kind = 'mock' as const;
  private cases = new Map<string, CaseView>();

  async updateRules(_body: RulesRequest): Promise<Rules> { throw new ApiError(503, null, 'La demostración no guarda políticas editoriales.'); }
  async connections(): Promise<Connections> { return { available: false, reason: 'Conexiones personales no disponibles en demostración.', profiles: [], activeProfileId: null }; }
  async startConnection(_body: ConnectionStart): Promise<Authorization> { throw new ApiError(503, null, 'Usa la aplicación local con la API real.'); }
  async selectConnection(_profileId: string): Promise<Connections> { throw new ApiError(503, null, 'Usa la aplicación local con la API real.'); }
  async connectionModels(): Promise<Models> { throw new ApiError(503, null, 'Usa la aplicación local con la API real.'); }
  async selectConnectionModel(_model: string): Promise<Models> { throw new ApiError(503, null, 'Usa la aplicación local con la API real.'); }
  async disconnect(_profileId: string): Promise<Disconnect> { throw new ApiError(503, null, 'Usa la aplicación local con la API real.'); }

  private getCaseSync(caseId: string): CaseView {
    const topicId = caseId.replace(/^case-/, '');
    if (!MOCK_SPECS.some((s) => s.id === topicId)) throw new ApiError(404, { code: 'caso_no_encontrado', message: 'Caso no encontrado', details: null });
    return this.cases.get(caseId) ?? blankCase(topicId);
  }

  private commit(c: CaseView, event: { kind: string; actor: string; comment?: string | null; from?: ReviewStatus | null; to?: ReviewStatus | null }): CaseView {
    const next: CaseView = {
      ...c,
      persisted: true,
      version: c.version + 1,
      updatedAt: now(),
      createdAt: c.createdAt ?? now(),
      statusLabel: STATUS_LABEL[c.status],
      allowedTransitions: TRANSITIONS[c.status],
      history: [
        ...c.history,
        {
          version: c.version + 1,
          at: now(),
          actor: event.actor,
          kind: event.kind,
          fromStatus: event.from ?? null,
          toStatus: event.to ?? null,
          comment: event.comment ?? null,
          draftNumber: c.currentDraft?.number ?? null,
          rulesVersion: c.rulesVersion,
        },
      ],
    };
    this.cases.set(next.caseId, next);
    return next;
  }

  async health() {
    await delay(40);
    return MOCK_HEALTH;
  }
  async rules() {
    return MOCK_RULES;
  }
  async snapshot() {
    return MOCK_SNAPSHOT;
  }

  async topics(f: TopicFilters): Promise<TopicsResponse> {
    await delay();
    const q = f.q?.trim().toLowerCase();
    const all = MOCK_SPECS.map((s) => buildDetail(s, this.getCaseSync(`case-${s.id}`)).summary);
    let items = all
      .filter((t) => f.scope === 'all' || t.category !== 'indeterminado')
      .filter((t) => !f.category || t.category === f.category)
      .filter((t) => !f.evidence || t.evidenceStatus === f.evidence)
      .filter((t) => !f.band || t.band === f.band)
      .filter((t) => !f.reviewStatus || t.reviewStatus === f.reviewStatus)
      .filter((t) => !q || t.title.toLowerCase().includes(q) || t.categoryLabel.toLowerCase().includes(q));
    items = items.sort((a, b) => b.score - a.score || b.urgency - a.urgency || a.id.localeCompare(b.id));
    const total = items.length;
    const ranked: TopicSummary[] = items.slice(0, f.limit ?? 5).map((t, i) => ({ ...t, rank: i + 1 }));
    const facet = (key: 'category' | 'evidenceStatus' | 'band' | 'reviewStatus') =>
      all.reduce<Record<string, number>>((acc, t) => ({ ...acc, [t[key]]: (acc[t[key]] ?? 0) + 1 }), {});
    return {
      snapshotId: MOCK_SNAPSHOT_ID,
      rulesVersion: MOCK_RULES_VERSION,
      dataMode: 'fixture',
      cutoffUtc: MOCK_CUTOFF,
      total,
      scope: f.scope ?? 'in_scope',
      outOfScopeCount: all.filter((t) => t.category === 'indeterminado').length,
      items: ranked,
      applied: { ...f },
      facets: { category: facet('category'), evidence: facet('evidenceStatus'), band: facet('band'), reviewStatus: facet('reviewStatus') },
    };
  }

  async topic(topicId: string): Promise<TopicDetail> {
    await delay();
    const spec = MOCK_SPECS.find((s) => s.id === topicId);
    if (!spec) throw new ApiError(404, { code: 'tema_no_encontrado', message: 'Tema no encontrado', details: null });
    return buildDetail(spec, this.getCaseSync(`case-${topicId}`));
  }

  async compose(req: QueryRequestBody, opts: { signal?: AbortSignal } = {}): Promise<ComposeResponse> {
    const response = await this.query(req, opts);
    return {
      response, answerMode: 'reglas', rulesAnswer: response.answer, provider: null, model: null, usage: null, attempts: 0,
      fallbackReason: 'sin_credenciales', fallbackDetail: 'La demostración no tiene un proveedor de IA conectado.', notices: [],
    };
  }

  async query(req: QueryRequestBody, opts: { signal?: AbortSignal } = {}): Promise<QueryResponse> {
    await delay(250);
    if (opts.signal?.aborted) throw new DOMException('Consulta cancelada', 'AbortError');
    const terms = req.question.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter((t) => t.length > 3);
    const base = {
      snapshotId: MOCK_SNAPSHOT_ID,
      rulesVersion: MOCK_RULES_VERSION,
      dataMode: 'fixture' as const,
      queryId: `mock-q-${Date.now()}`,
      question: req.question,
      warnings: ['Respuesta simulada por el frontend con datos de demostración.'],
      resolvedQuestion: null,
      followUpContext: null,
      followUpSuggestions: [] as string[],
    };
    const topics = MOCK_SPECS.map((s) => buildDetail(s, this.getCaseSync(`case-${s.id}`)));
    const hits = topics.flatMap((t) =>
      t.articles
        .map((a) => {
          const hay = `${a.title} ${t.summary.categoryLabel}`.toLowerCase();
          const matched = terms.filter((term) => hay.includes(term));
          return { t, a, matched };
        })
        .filter((x) => x.matched.length > 0 && (!req.topicId || x.t.summary.id === req.topicId)),
    );
    const asksNumber = /cifra|porcentaje|cu[aá]nto|exacto|n[uú]mero/.test(req.question.toLowerCase());
    const retrieval = { corpusSize: topics.reduce((a, t) => a + t.articles.length, 0), coverage: terms.length ? Math.min(1, hits.length / terms.length) : 0, matchedTerms: [...new Set(hits.flatMap((h) => h.matched))], method: 'mock: coincidencia de palabras', tookMs: 5 };
    if (!hits.length || (asksNumber && !hits.some((h) => h.t.contradictions.length))) {
      return {
        ...base,
        intent: 'busqueda',
        answerStatus: 'abstencion',
        answer: 'No puedo responder con la evidencia disponible: no encontré fuentes que respalden esa consulta.',
        abstentionReason: 'Ningún documento del corpus de demostración respalda la pregunta.',
        missing: ['Fuente primaria o noticia que contenga la cifra o el hecho consultado.'],
        citations: [],
        contradictions: [],
        hits: [],
        relatedTopicIds: [],
        retrieval,
      };
    }
    const top = hits.slice(0, req.limit ?? 5);
    const contradictions = [...new Map(top.flatMap((h) => h.t.contradictions).map((c) => [c.id, c])).values()];
    return {
      ...base,
      intent: /verific|falta/.test(req.question.toLowerCase()) ? 'verificaciones' : /econom|pib|indicador/.test(req.question.toLowerCase()) ? 'contexto_economico' : /agenda|cinco|temas/.test(req.question.toLowerCase()) ? 'agenda' : 'busqueda',
      answerStatus: contradictions.length ? 'contradiccion' : 'respondida',
      answer: contradictions.length
        ? 'Hay versiones incompatibles entre fuentes (datos de ejemplo). Se muestran ambas; la verificación está pendiente.'
        : `Encontré ${top.length} documento(s) de ejemplo relacionados. ${top[0]?.t.whatIsReported ?? ''}`,
      abstentionReason: null,
      missing: [...new Set(top.flatMap((h) => h.t.pendingVerifications))].slice(0, 3),
      citations: top.map((h) => ({ evidenceId: h.a.id, field: 'title', passage: h.a.title, title: h.a.title, url: h.a.url })),
      contradictions,
      hits: top.map((h) => ({
        evidenceId: h.a.id,
        kind: 'article',
        title: h.a.title,
        url: h.a.url,
        outlet: h.a.outlet,
        publishedAt: h.a.publishedAt,
        clusterId: h.a.clusterId,
        bm25: 1,
        fuzzy: 0.8,
        relevance: 0.9,
        snippet: h.a.title,
        suspiciousInstructions: h.a.suspiciousInstructions,
      })),
      relatedTopicIds: [...new Set(top.map((h) => h.t.summary.id))],
      retrieval,
    };
  }

  async createDraft(topicId: string, provider: DraftProviderChoice = 'auto'): Promise<DraftResponse> {
    await delay(400);
    const detail = await this.topic(topicId);
    const c = this.getCaseSync(`case-${topicId}`);
    const number = c.drafts.length + 1;
    const claims: Claim[] = detail.supportedClaims.length ? detail.supportedClaims : [];
    const brief = `Borrador de plantilla (mock) sobre «${detail.summary.title}». ${detail.whatIsReported} Basado únicamente en titular/metadatos.`;
    const script = 'Plantilla de guion (mock): presentar el tema, atribuir cada afirmación a su fuente, y cerrar con lo que falta verificar. ' + 'Sin entrevistas ni citas inventadas. '.repeat(3);
    const social = `Tema en revisión: ${detail.summary.title}. Aún hay verificaciones pendientes.`;
    const draft: DraftRecord = {
      draftId: `mock-draft-${topicId}-${number}`,
      number,
      createdAt: now(),
      editedAt: null,
      editedBy: null,
      provider: 'plantilla',
      model: null,
      generationMode: 'plantilla',
      generationLabel: 'Construido mediante plantilla',
      fallbackReason: provider === 'auto' || provider === 'plantilla' ? (provider === 'plantilla' ? 'solicitado' : 'proveedor_no_disponible') : 'proveedor_no_disponible',
      fallbackDetail: provider === 'plantilla' ? null : 'Modo mock del frontend: no hay modelo conectado.',
      recoveredFromDraftId: null,
      previousDraftId: null,
      usage: null,
      snapshotId: MOCK_SNAPSHOT_ID,
      rulesVersion: MOCK_RULES_VERSION,
      package: {
        brief,
        proposedTitle: detail.summary.title.replace('Ejemplo · ', ''),
        publicInterestAngle: 'Interés público: explicar qué se sabe y qué falta comprobar (ejemplo).',
        researchQuestions: ['¿Qué fuente primaria confirma el hecho?', '¿Hay una segunda procedencia independiente?', '¿Qué dato oficial lo contextualiza sin presentarlo como cifra de hoy?'],
        pendingVerifications: detail.pendingVerifications,
        script,
        socialCopy: social,
        claims,
        headlineOnly: true,
        headlineOnlyNotice: 'basado únicamente en titular/metadatos',
        limitations: ['Borrador de plantilla generado por el mock del frontend.'],
      },
      validation: validate(brief, script, social, claims),
    };
    const next = this.commit({ ...c, drafts: [...c.drafts, draft], currentDraft: draft }, { kind: 'borrador_creado', actor: 'sistema' });
    return { case: next, draft, notices: ['Datos de demostración del frontend: este borrador no usa noticias reales.'] };
  }

  async saveDraft(caseId: string, body: DraftEditRequest): Promise<CaseView> {
    await delay();
    const c = this.getCaseSync(caseId);
    this.checkVersion(c, body.expectedVersion);
    if (!c.currentDraft) throw new ApiError(422, { code: 'sin_borrador', message: 'Aún no hay borrador que editar', details: null });
    const p = c.currentDraft.package;
    const pkg = {
      ...p,
      brief: body.brief ?? p.brief,
      script: body.script ?? p.script,
      socialCopy: body.socialCopy ?? p.socialCopy,
      proposedTitle: body.proposedTitle ?? p.proposedTitle,
      publicInterestAngle: body.publicInterestAngle ?? p.publicInterestAngle,
      researchQuestions: body.researchQuestions ?? p.researchQuestions,
      pendingVerifications: body.pendingVerifications ?? p.pendingVerifications,
      claims: (body.claims as Claim[] | null | undefined)?.map((x) => ({ ...x, citations: (x.citations ?? []).map((ct) => ({ ...ct, passage: ct.passage ?? null })) })) ?? p.claims,
    };
    const number = c.drafts.length + 1;
    const draft: DraftRecord = { ...c.currentDraft, draftId: `mock-draft-${c.topicId}-${number}`, number, previousDraftId: c.currentDraft.draftId, package: pkg, editedAt: now(), editedBy: body.editor, validation: validate(pkg.brief, pkg.script, pkg.socialCopy, pkg.claims) };
    return this.commit({ ...c, currentDraft: draft, drafts: [...c.drafts, draft] }, { kind: 'borrador_editado', actor: body.editor });
  }

  private checkVersion(c: CaseView, expected: number) {
    if (c.version !== expected)
      throw new ApiError(409, { code: 'conflicto_de_version', message: `Otra persona (o pestaña) cambió el caso: versión actual ${c.version}, la tuya ${expected}.`, details: { currentVersion: c.version } });
  }

  async review(caseId: string, body: ReviewRequest): Promise<CaseView> {
    await delay();
    const c = this.getCaseSync(caseId);
    this.checkVersion(c, body.expectedVersion);
    if (!body.reviewer.trim()) throw new ApiError(422, { code: 'revisor_requerido', message: 'Indica la persona responsable', details: null });
    if (!TRANSITIONS[c.status].includes(body.status)) throw new ApiError(422, { code: 'transicion_invalida', message: `No se permite pasar de «${STATUS_LABEL[c.status]}» a «${STATUS_LABEL[body.status]}»`, details: null });
    if ((body.status === 'requiere_evidencia' || body.status === 'descartado') && !body.comment?.trim()) throw new ApiError(422, { code: 'comentario_requerido', message: 'Este estado exige un comentario', details: null });
    if (body.primarySourceConfirmed && !body.comment?.trim()) throw new ApiError(422, { code: 'comentario_requerido', message: 'Identifica la fuente primaria y el hecho respaldado.', details: null });
    if (body.status === 'aprobado_como_borrador') {
      if (!c.currentDraft) throw new ApiError(422, { code: 'sin_borrador', message: 'No se puede aprobar sin un borrador', details: null });
      const topic = MOCK_SPECS.find((s) => `case-${s.id}` === caseId);
      if (topic?.evidence === 'insuficiente' && !body.evidenceConfirmed) throw new ApiError(422, { code: 'evidencia_insuficiente', message: 'La evidencia es insuficiente: confirma explícitamente la suficiencia con un comentario, o pide más evidencia.', details: null });
    }
    const next = this.commit(
      { ...c, status: body.status, reviewer: body.reviewer, evidenceConfirmed: body.evidenceConfirmed ?? c.evidenceConfirmed, evidenceConfirmedBy: body.evidenceConfirmed ? body.reviewer : c.evidenceConfirmedBy,
        primarySourceConfirmed: body.primarySourceConfirmed ?? c.primarySourceConfirmed,
        primarySourceConfirmedBy: body.primarySourceConfirmed !== undefined && body.primarySourceConfirmed !== null ? body.reviewer : c.primarySourceConfirmedBy,
        primarySourceReason: body.primarySourceConfirmed !== undefined && body.primarySourceConfirmed !== null ? body.comment ?? null : c.primarySourceReason,
      },
      { kind: 'revision', actor: body.reviewer, comment: body.comment, from: c.status, to: body.status },
    );
    return next;
  }

  async setImpact(topicId: string, body: ImpactRequest): Promise<CaseView> {
    await delay();
    const c = this.getCaseSync(`case-${topicId}`);
    this.checkVersion(c, body.expectedVersion);
    return this.commit(
      { ...c, impact: { level: body.level, origin: 'asignacion_editorial', justification: body.justification, evidenceIds: body.evidenceIds, author: body.author, reason: body.reason, at: now(), version: c.version + 1 } },
      { kind: 'impacto', actor: body.author, comment: body.reason },
    );
  }

  async getCase(caseId: string) {
    await delay(40);
    return this.getCaseSync(caseId);
  }

  async exportCase(caseId: string): Promise<ExportResponse> {
    await delay();
    const c = this.getCaseSync(caseId);
    const p = c.currentDraft?.package;
    return {
      caseId,
      filename: `${caseId}.md`,
      generatedAt: now(),
      snapshotId: MOCK_SNAPSHOT_ID,
      rulesVersion: MOCK_RULES_VERSION,
      markdown: `> DATOS DE DEMOSTRACIÓN DEL FRONTEND (no reales)\n\n# ${p?.proposedTitle ?? caseId}\n\nEstado: ${STATUS_LABEL[c.status]}\n\n${p?.brief ?? '_Sin borrador._'}\n`,
    };
  }
}

function validate(brief: string, script: string, copy: string, claims: Claim[]): DraftRecord['validation'] {
  const issues: DraftRecord['validation']['issues'] = [];
  const wc = { brief: words(brief), script: words(script), socialCopy: words(copy) };
  if (wc.brief > 250) issues.push({ code: 'brief_largo', severity: 'error', message: `El brief tiene ${wc.brief} palabras (máx. 250).`, claimId: null });
  if (wc.socialCopy > 80) issues.push({ code: 'copy_largo', severity: 'error', message: `El copy tiene ${wc.socialCopy} palabras (máx. 80).`, claimId: null });
  const secs = wc.script / 2.5;
  if (secs < 45 || secs > 60) issues.push({ code: 'guion_duracion', severity: 'warning', message: `Guion de ~${Math.round(secs)} s (objetivo 45–60 s).`, claimId: null });
  const noCite = claims.filter((c) => !c.citations.length);
  noCite.forEach((c) => issues.push({ code: 'sin_cita', severity: 'error', message: 'Afirmación sin cita.', claimId: c.id }));
  return {
    ok: !issues.some((i) => i.severity === 'error'),
    citationCoverage: claims.length ? (claims.length - noCite.length) / claims.length : 1,
    factualCitationCoverage: claims.length ? (claims.length - noCite.length) / claims.length : null,
    issues,
    note: 'Una cita estructuralmente válida no prueba sustento: requiere revisión humana.',
    rejectedClaimIds: noCite.map((c) => c.id),
    scriptSecondsEstimate: Math.round(secs),
    wordCounts: wc,
  };
}
