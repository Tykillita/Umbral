// DATOS DE DEMOSTRACIÓN DEL FRONTEND. NO son noticias ni cifras reales.
// Se usan solo cuando la API no responde (PUBLIC_API_MODE=mock|auto) y la interfaz lo declara con un banner.
// Para reemplazarlos: ponga PUBLIC_API_MODE=live; esta carpeta no se importa en ese modo salvo por carga dinámica.
import type {
  Category,
  Claim,
  Contradiction,
  EvidenceArticle,
  EvidenceStatus,
  Health,
  IndicatorPoint,
  Rules,
  ScoreBand,
  ScoreComponent,
  ScoreDetail,
  SnapshotInfo,
  TopicDetail,
} from '../api/types';

export const MOCK_SNAPSHOT_ID = '00000000-mock0000';
export const MOCK_RULES_VERSION = 'scoring-v1';
export const MOCK_CUTOFF = '2026-10-07T12:00:00Z';

export const MOCK_LABEL = 'MOCK del frontend';

const WEIGHTS = { R: 30, I: 25, U: 20, N: 15, E: 10 } as const;
const NAMES = { R: 'Relevancia', I: 'Impacto', U: 'Urgencia', N: 'Novedad', E: 'Evidencia' } as const;

function comp(
  key: keyof typeof WEIGHTS,
  value: number,
  rule: string,
  justification: string,
  limits: string[] = [],
  evidenceIds: string[] = [],
): ScoreComponent {
  return {
    key,
    label: NAMES[key],
    weight: WEIGHTS[key],
    value,
    points: Math.round(WEIGHTS[key] * value * 100) / 100,
    rule,
    justification,
    limits,
    evidenceIds,
  };
}

function bandOf(total: number): ScoreBand {
  return total >= 70 ? 'alto' : total >= 40 ? 'medio' : 'bajo';
}

function art(
  id: string,
  title: string,
  outlet: string,
  publishedAt: string | null,
  extra: Partial<EvidenceArticle> = {},
): EvidenceArticle {
  return {
    id,
    kind: 'article',
    title,
    url: `https://ejemplo.invalid/${id}`,
    domain: 'ejemplo.invalid',
    outlet,
    isTvn: outlet.startsWith('TVN'),
    language: 'es',
    publishedAt,
    publishedAtBasis: publishedAt ? 'rss_pubdate' : 'unknown',
    detectedAt: publishedAt,
    extractedAt: MOCK_CUTOFF,
    origin: outlet.includes('agencia') ? 'agency:agencia-ejemplo' : `outlet:${id}`,
    originKey: outlet.includes('agencia') ? 'agency:agencia-ejemplo' : `outlet:${id}`,
    originKnown: true,
    category: 'indeterminado',
    categoryProbability: null,
    classifier: 'mock',
    geoRelevance: 'panama',
    geoEvidence: [],
    clusterId: null,
    scopeText: 'basado únicamente en titular/metadatos',
    suspiciousInstructions: false,
    sponsoredContent: false,
    flags: [],
    dataOrigin: 'fixture',
    ...extra,
  };
}

function ind(
  id: string,
  indicatorId: string,
  name: string,
  country: string,
  year: number,
  value: number | null,
  unit: string,
): IndicatorPoint {
  return {
    id,
    kind: 'indicator',
    indicatorId,
    indicatorName: name,
    countryIso3: country,
    countryName: country,
    year,
    value,
    unit,
    isMissing: value === null,
    note:
      value === null
        ? `Sin dato para ${country} en ${year}; no se rellena con cero.`
        : `Dato anual de ${year}, no una medición de hoy. Valor de ejemplo.`,
    sourceUrl: 'https://data.worldbank.org/',
    license: 'CC BY 4.0',
    extractedAt: MOCK_CUTOFF,
    dataOrigin: 'fixture',
  };
}

type Spec = {
  id: string;
  title: string;
  category: Category;
  categoryLabel: string;
  scores: { R: number; I: number; U: number; N: number; E: number };
  impactOrigin: 'propuesta_automatica' | 'asignacion_editorial';
  evidence: EvidenceStatus;
  articles: EvidenceArticle[];
  indicators: IndicatorPoint[];
  claims: Claim[];
  contradictions?: Contradiction[];
  pending: string[];
  whatIsReported: string;
  recirculation?: boolean;
  headlineOnly?: boolean;
  topReason: string;
};

const SPECS: Spec[] = [
  {
    id: 'tema-mock-001',
    title: 'Ejemplo · Ajuste en la programación de tránsito del Canal',
    category: 'logistica_canal',
    categoryLabel: 'Logística/Canal',
    scores: { R: 1, I: 1, U: 1, N: 1, E: 0.67 },
    impactOrigin: 'asignacion_editorial',
    evidence: 'suficiente',
    articles: [
      art('mock-a1', 'Ejemplo: Canal anuncia ajuste en reservas de tránsito', 'TVN (ejemplo)', '2026-10-07T09:10:00Z', { isTvn: true, category: 'logistica_canal', clusterId: 'cl-1', categoryProbability: 0.81 }),
      art('mock-a2', 'Ejemplo: Operadores reaccionan al ajuste de tránsito', 'Medio de ejemplo B', '2026-10-07T10:30:00Z', { category: 'logistica_canal', clusterId: 'cl-1', categoryProbability: 0.77 }),
      art('mock-a3', 'Ejemplo: Ajuste de tránsito del Canal (replicado)', 'Medio C (agencia ejemplo)', '2026-10-07T10:45:00Z', { category: 'logistica_canal', clusterId: 'cl-1' }),
    ],
    indicators: [ind('mock-i1', 'NE.EXP.GNFS.ZS', 'Exportaciones de bienes y servicios (% del PIB)', 'PAN', 2023, 55.0, '% del PIB')],
    claims: [
      { id: 'c1', type: 'hecho', text: 'Un medio reporta un ajuste en la programación de tránsito (afirmación de ejemplo).', citations: [{ evidenceId: 'mock-a1', field: 'title', passage: 'Ejemplo: Canal anuncia ajuste en reservas de tránsito' }] },
      { id: 'c2', type: 'declaracion', text: 'Operadores habrían reaccionado al ajuste, según un segundo medio (ejemplo).', citations: [{ evidenceId: 'mock-a2', field: 'title', passage: null }] },
    ],
    pending: ['Confirmar la fecha de entrada en vigor con comunicado oficial.', 'Verificar el alcance sobre cada tipo de buque.'],
    whatIsReported: 'Dato de ejemplo: se reporta un ajuste de programación de tránsito. No es una noticia real.',
    topReason: 'Relación directa con Panamá, publicación en las últimas 24 h y dos procedencias independientes.',
  },
  {
    id: 'tema-mock-002',
    title: 'Ejemplo · Posible cambio en tarifas de servicios públicos',
    category: 'servicios_publicos',
    categoryLabel: 'Servicios públicos',
    scores: { R: 1, I: 1, U: 1, N: 1, E: 0.33 },
    impactOrigin: 'propuesta_automatica',
    evidence: 'insuficiente',
    headlineOnly: true,
    articles: [art('mock-b1', 'Ejemplo: Se evalúa ajuste a tarifas de servicios', 'Medio de ejemplo D', '2026-10-07T08:00:00Z', { category: 'servicios_publicos' })],
    indicators: [],
    claims: [{ id: 'c1', type: 'hecho', text: 'Un único medio reporta que se evalúa un ajuste (ejemplo).', citations: [{ evidenceId: 'mock-b1', field: 'title', passage: null }] }],
    pending: ['Buscar fuente primaria (resolución o comunicado).', 'Buscar un segundo medio independiente.'],
    whatIsReported: 'Dato de ejemplo: una sola fuente, solo titular. Prioridad alta con evidencia insuficiente.',
    topReason: 'Alta prioridad por urgencia y relevancia, pero con una sola procedencia: requiere investigación.',
  },
  {
    id: 'tema-mock-003',
    title: 'Ejemplo · Versiones distintas sobre llegada de turistas',
    category: 'turismo',
    categoryLabel: 'Turismo',
    scores: { R: 1, I: 0.5, U: 0.5, N: 1, E: 0.67 },
    impactOrigin: 'propuesta_automatica',
    evidence: 'parcial',
    articles: [
      art('mock-c1', 'Ejemplo: La llegada de turistas subió, según medio E', 'Medio de ejemplo E', '2026-10-05T14:00:00Z', { category: 'turismo' }),
      art('mock-c2', 'Ejemplo: La llegada de turistas bajó, según medio F', 'Medio de ejemplo F', '2026-10-06T09:00:00Z', { category: 'turismo' }),
    ],
    indicators: [ind('mock-i2', 'IT.NET.USER.ZS', 'Individuos que usan Internet (% de la población)', 'PAN', 2023, null, '% de la población')],
    claims: [{ id: 'c1', type: 'declaracion', text: 'Cada medio atribuye una tendencia opuesta (ejemplo).', citations: [{ evidenceId: 'mock-c1', field: 'title', passage: null }, { evidenceId: 'mock-c2', field: 'title', passage: null }] }],
    contradictions: [
      {
        id: 'k1',
        description: 'Dos medios describen tendencias incompatibles (ejemplo).',
        status: 'pendiente_de_revision',
        pendingVerification: 'Contrastar con estadística oficial del período.',
        versions: [
          { evidenceId: 'mock-c1', outlet: 'Medio de ejemplo E', publishedAt: '2026-10-05T14:00:00Z', scope: 'titular', statement: 'La llegada subió.' },
          { evidenceId: 'mock-c2', outlet: 'Medio de ejemplo F', publishedAt: '2026-10-06T09:00:00Z', scope: 'titular', statement: 'La llegada bajó.' },
        ],
      },
    ],
    pending: ['Resolver la contradicción con cifras oficiales.'],
    whatIsReported: 'Dato de ejemplo: dos versiones incompatibles. El sistema no elige una.',
    topReason: 'Hay contradicción visible entre fuentes; la revisión humana decide.',
  },
  {
    id: 'tema-mock-004',
    title: 'Ejemplo · Nota antigua recirculada sobre sismo regional',
    category: 'eventos_naturales',
    categoryLabel: 'Eventos naturales',
    scores: { R: 0.5, I: 0.5, U: 0, N: 0, E: 0.33 },
    impactOrigin: 'propuesta_automatica',
    evidence: 'insuficiente',
    recirculation: true,
    headlineOnly: true,
    articles: [art('mock-d1', 'Ejemplo: Sismo sacude la región (nota de hace meses recirculada)', 'Medio de ejemplo G', '2026-03-12T10:00:00Z', { category: 'eventos_naturales', geoRelevance: 'regional' })],
    indicators: [],
    claims: [{ id: 'c1', type: 'hecho', text: 'La nota original es de marzo de 2026; no es un evento nuevo (ejemplo).', citations: [{ evidenceId: 'mock-d1', field: 'publishedAt', passage: null }] }],
    pending: ['Confirmar que no hay un evento sísmico reciente.'],
    whatIsReported: 'Dato de ejemplo: nota antigua recirculada; se muestra la fecha original.',
    topReason: 'Recirculación: novedad y urgencia en cero.',
  },
  {
    id: 'tema-mock-005',
    title: 'Ejemplo · Informe económico trimestral y contexto oficial',
    category: 'economia',
    categoryLabel: 'Economía',
    scores: { R: 1, I: 0.5, U: 0.5, N: 1, E: 1 },
    impactOrigin: 'propuesta_automatica',
    evidence: 'suficiente',
    articles: [
      art('mock-e1', 'Ejemplo: Informe trimestral muestra desaceleración moderada', 'TVN (ejemplo)', '2026-10-03T16:00:00Z', { isTvn: true, category: 'economia' }),
      art('mock-e2', 'Ejemplo: Analistas comentan el informe trimestral', 'Medio de ejemplo H', '2026-10-04T11:00:00Z', { category: 'economia' }),
    ],
    indicators: [
      ind('mock-i3', 'NY.GDP.MKTP.KD.ZG', 'Crecimiento del PIB (% anual)', 'PAN', 2023, 7.3, '% anual'),
      ind('mock-i4', 'NY.GDP.MKTP.KD.ZG', 'Crecimiento del PIB (% anual)', 'CRI', 2023, 5.1, '% anual'),
    ],
    claims: [
      { id: 'c1', type: 'hecho', text: 'Un medio reporta una desaceleración moderada (ejemplo).', citations: [{ evidenceId: 'mock-e1', field: 'title', passage: null }] },
      { id: 'c2', type: 'inferencia', text: 'El crecimiento anual de 2023 es histórico y no describe el trimestre actual (valor de ejemplo).', citations: [{ evidenceId: 'mock-i3', field: 'value', passage: null }] },
    ],
    pending: ['Obtener el informe oficial citado por el medio.'],
    whatIsReported: 'Dato de ejemplo: informe trimestral con contexto del Banco Mundial (valores ficticios).',
    topReason: 'Contexto oficial disponible, pero con dato anual histórico.',
  },
  {
    id: 'tema-mock-006',
    title: 'Ejemplo · Fuente con instrucciones sospechosas sobre regulación',
    category: 'regulacion',
    categoryLabel: 'Regulación',
    scores: { R: 0.5, I: 0.25, U: 0.5, N: 1, E: 0.33 },
    impactOrigin: 'propuesta_automatica',
    evidence: 'insuficiente',
    headlineOnly: true,
    articles: [
      art('mock-f1', 'Ejemplo: Nota regulatoria que pide ignorar las reglas del sistema', 'Medio de ejemplo I', '2026-10-06T07:00:00Z', {
        category: 'regulacion',
        geoRelevance: 'regional',
        suspiciousInstructions: true,
        flags: ['instrucciones_en_contenido'],
      }),
    ],
    indicators: [],
    claims: [],
    pending: ['Revisar manualmente la fuente: el sistema la trata como contenido no confiable.'],
    whatIsReported: 'Dato de ejemplo: una fuente contiene texto dirigido al sistema; se ignora como instrucción.',
    topReason: 'Fuente marcada como no confiable; no se ejecutó ninguna instrucción.',
  },
];

export function buildScore(spec: Spec): ScoreDetail {
  const R = comp('R', spec.scores.R, spec.scores.R === 1 ? 'Panamá: 1' : spec.scores.R === 0.5 ? 'Relación regional: 0,5' : 'Sin relación: 0', 'Calculado sobre la geografía del tema (mock).', ['Clasificación mock; no proviene de Laya.']);
  const I = comp(
    'I',
    spec.scores.I,
    'Bajo 0,25 · medio 0,5 · alto 1',
    spec.impactOrigin === 'asignacion_editorial' ? 'Asignación editorial con justificación (mock).' : 'Propuesta automática; requiere confirmación editorial.',
    spec.impactOrigin === 'propuesta_automatica' ? ['Propuesta automática: confirme el impacto con evidencia.'] : [],
  );
  const U = comp('U', spec.scores.U, '≤24 h: 1 · ≤7 días: 0,5 · antes: 0', 'Contra la fecha de corte del snapshot.', spec.scores.U === 0 ? ['Publicación original antigua o desconocida: urgencia 0.'] : []);
  const N = comp('N', spec.scores.N, 'Evento nuevo: 1 · recirculación: 0', spec.recirculation ? 'Recirculación de una nota antigua.' : 'Evento nuevo en el corpus.');
  const E = comp('E', spec.scores.E, 'Sin procedencia 0 · una 0,33 · dos independientes 0,67 · primaria + original 1', 'Una agencia replicada cuenta como una procedencia.', spec.scores.E < 1 ? ['Sin fuente primaria pertinente enlazada.'] : []);
  const components = [R, I, U, N, E];
  const total = Math.round(components.reduce((a, c) => a + c.points, 0) * 10) / 10;
  return {
    band: bandOf(total),
    components,
    disclaimer: 'El puntaje ordena la atención; no es una probabilidad de verdad ni habilita publicación.',
    formula: 'P = 30R + 25I + 20U + 15N + 10E',
    idTiebreak: spec.id,
    rulesVersion: MOCK_RULES_VERSION,
    total,
    urgencyTiebreak: spec.scores.U,
  };
}

export function buildDetail(spec: Spec, caseView: TopicDetail['case']): TopicDetail {
  const score = buildScore(spec);
  const provenances = new Set(spec.articles.map((a) => a.originKey));
  const needsInvestigation = score.band === 'alto' && spec.evidence === 'insuficiente';
  return {
    snapshotId: MOCK_SNAPSHOT_ID,
    cutoffUtc: MOCK_CUTOFF,
    rulesVersion: MOCK_RULES_VERSION,
    dataMode: 'fixture',
    summary: {
      id: spec.id,
      title: spec.title,
      category: spec.category,
      categoryLabel: spec.categoryLabel,
      score: score.total,
      band: score.band,
      scoreComponents: score.components,
      evidenceStatus: spec.evidence,
      evidenceStatusLabel: spec.evidence,
      reviewStatus: caseView.status,
      reviewStatusLabel: caseView.statusLabel,
      rank: null,
      articleCount: spec.articles.length,
      independentProvenances: provenances.size,
      firstPublishedAt: spec.articles.map((a) => a.publishedAt).filter(Boolean).sort()[0] ?? null,
      lastPublishedAt: spec.articles.map((a) => a.publishedAt).filter(Boolean).sort().at(-1) ?? null,
      geoRelevance: spec.articles[0]?.geoRelevance ?? 'panama',
      relevanceReason: 'Relación de ejemplo con Panamá; dato simulado.',
      outOfScope: spec.category === 'indeterminado',
      possibleSponsored: false,
      hasContradictions: (spec.contradictions?.length ?? 0) > 0,
      hasSuspiciousSource: spec.articles.some((a) => a.suspiciousInstructions),
      headlineOnly: spec.headlineOnly ?? true,
      isRecirculation: spec.recirculation ?? false,
      needsInvestigation,
      topReason: spec.topReason,
      urgency: spec.scores.U,
    },
    whatIsReported: spec.whatIsReported,
    reporters: spec.articles.map((a) => ({
      outlet: a.outlet,
      origin: a.originKey,
      originKnown: true,
      role: a.originKey.startsWith('agency:') ? 'replica' : 'original',
      evidenceIds: [a.id],
    })),
    articles: spec.articles,
    officialContext: {
      indicators: spec.indicators,
      relationRationale: spec.indicators.length ? 'Relación temática con el indicador (mock).' : 'No existe una relación sustentada con un indicador oficial; no se fuerza.',
      limitations: spec.indicators.length ? ['Datos anuales históricos; no describen la situación de hoy.', 'Valores ficticios del mock.'] : [],
    },
    supportedClaims: spec.claims,
    contradictions: spec.contradictions ?? [],
    pendingVerifications: spec.pending,
    score,
    impact: {
      level: spec.scores.I >= 1 ? 'alto' : spec.scores.I >= 0.5 ? 'medio' : 'bajo',
      origin: spec.impactOrigin,
      justification: spec.impactOrigin === 'asignacion_editorial' ? 'Asignación editorial de ejemplo.' : 'Propuesta automática (mock).',
      evidenceIds: spec.articles.slice(0, 1).map((a) => a.id),
      author: null,
      at: null,
      reason: null,
      version: 0,
    },
    evidence: {
      status: spec.evidence,
      statusLabel: spec.evidence,
      rationale:
        spec.evidence === 'suficiente'
          ? 'Hay procedencias independientes y contexto utilizable para un borrador.'
          : spec.evidence === 'parcial'
            ? 'Hay evidencia, pero con vacíos por resolver.'
            : 'Evidencia insuficiente: se necesita fuente primaria o corroboración independiente.',
      gaps:
        spec.evidence === 'suficiente'
          ? []
          : [{ code: 'sin_fuente_primaria', message: 'No hay fuente primaria pertinente enlazada.' }, ...(provenances.size < 2 ? [{ code: 'una_procedencia', message: 'Solo una procedencia independiente.' }] : [])],
      independentProvenances: provenances.size,
      primarySourceLinked: false,
      officialContextLinked: spec.indicators.length > 0,
      possibleSponsored: false,
      headlineOnly: spec.headlineOnly ?? true,
      reviewerConfirmed: null,
      reviewerConfirmedBy: null,
    },
    recommendedAction: needsInvestigation
      ? 'Requiere investigación: prioridad alta, pero la evidencia es insuficiente. No habilita publicación.'
      : 'Revisar la ficha, confirmar el impacto y generar un borrador para revisión humana.',
    warnings: ['Datos de demostración del frontend: no son noticias ni cifras reales.', ...(spec.articles.some((a) => a.suspiciousInstructions) ? ['Una fuente contiene instrucciones; se trata como contenido no confiable.'] : [])],
    case: caseView,
  };
}

export const MOCK_SPECS = SPECS;

export const MOCK_HEALTH: Health = {
  snapshotStale: false, snapshotRefreshError: null, snapshotLastCheckedAt: null, deployCommit: null,
  apiVersion: 'mock-frontend',
  authMode: 'local',
  classifier: 'mock (sin Laya)',
  containsFixtures: true,
  counts: { topics: SPECS.length, articles: SPECS.reduce((a, s) => a + s.articles.length, 0) },
  cutoffUtc: MOCK_CUTOFF,
  dataMode: 'fixture',
  integrity: {
    checkedAt: MOCK_CUTOFF,
    errors: [],
    filesChecked: 0,
    manifestVerified: false,
    predictionsHashVerified: null,
    predictionsSha256: null,
  },
  localMode: true,
  notes: ['Respuesta simulada por el frontend porque la API no está disponible.'],
  offline: false,
  persistence: 'memoria del navegador (mock)',
  provisional: true,
  providers: [
    { name: 'plantilla', mode: 'plantilla', available: true, external: false, localOnly: false, model: null, reason: null, signIn: null, account: null },
    { name: 'gemini', mode: 'modelo', available: false, external: true, localOnly: false, model: null, reason: 'No disponible en modo mock', signIn: null, account: null },
  ],
  rulesVersion: MOCK_RULES_VERSION,
  serverTimeUtc: MOCK_CUTOFF,
  snapshotId: MOCK_SNAPSHOT_ID,
  status: 'mock',
};

export const MOCK_RULES: Rules = {
  version: 0,
  history: [],
  rulesVersion: MOCK_RULES_VERSION,
  formula: 'P = 30R + 25I + 20U + 15N + 10E',
  weights: WEIGHTS,
  bands: { bajo: '[0,40)', medio: '[40,70)', alto: '[70,100]' },
  rules: {},
  changelog: [],
};

export const MOCK_SNAPSHOT: SnapshotInfo = {
  snapshotId: MOCK_SNAPSHOT_ID,
  dataMode: 'fixture',
  integrity: MOCK_HEALTH.integrity,
  manifest: { snapshotId: MOCK_SNAPSHOT_ID, version: 'mock', provisional: true, containsFixtures: true, cutoffUtc: MOCK_CUTOFF },
  metrics: null,
  qualityReport: null,
  sources: [
    { id: 'mock', name: 'Datos de demostración del frontend', url: null, license: 'N/A', coverage: 'Ficticio' },
  ],
};
