import type {
  AnswerStatus,
  Category,
  ComposeProvider,
  ClaimType,
  DataMode,
  DraftProviderChoice,
  EvidenceStatus,
  FallbackReason,
  GenerationMode,
  ReviewStatus,
  ScoreBand,
} from './api/types';

export const CATEGORY_LABEL: Record<Category, string> = {
  economia: 'Economía',
  logistica_canal: 'Logística/Canal',
  turismo: 'Turismo',
  servicios_publicos: 'Servicios públicos',
  eventos_naturales: 'Eventos naturales',
  regulacion: 'Regulación',
  indeterminado: 'Indeterminado',
};

export const EVIDENCE_LABEL: Record<EvidenceStatus, string> = {
  insuficiente: 'Evidencia insuficiente',
  parcial: 'Evidencia parcial',
  suficiente: 'Suficiente para el borrador',
};

export const BAND_LABEL: Record<ScoreBand, string> = {
  bajo: 'Prioridad baja [0–40)',
  medio: 'Prioridad media [40–70)',
  alto: 'Prioridad alta [70–100]',
};

export const BAND_SHORT: Record<ScoreBand, string> = { bajo: 'Baja', medio: 'Media', alto: 'Alta' };

export const REVIEW_LABEL: Record<ReviewStatus, string> = {
  nuevo: 'Nuevo',
  en_revision: 'En revisión',
  requiere_evidencia: 'Requiere evidencia',
  aprobado_como_borrador: 'Aprobado como borrador',
  descartado: 'Descartado',
};

export const CLAIM_LABEL: Record<ClaimType, string> = {
  hecho: 'Hecho',
  declaracion: 'Declaración',
  inferencia: 'Inferencia',
  hipotesis: 'Hipótesis',
};

export const CLAIM_HELP: Record<ClaimType, string> = {
  hecho: 'Respaldado por un campo o pasaje citado.',
  declaracion: 'Atribuida a quien la hizo; no es un hecho probado.',
  inferencia: 'Deducción del sistema; no está en la fuente.',
  hipotesis: 'Conjetura que requiere comprobación.',
};

export const GENERATION_LABEL: Record<GenerationMode, string> = {
  modelo: 'Generado por un modelo',
  recuperado: 'Recuperado de una ejecución anterior',
  plantilla: 'Construido con plantilla',
};

export const ANSWER_LABEL: Record<AnswerStatus, string> = {
  respondida: 'Respuesta con evidencia',
  parcial: 'Respuesta parcial',
  contradiccion: 'Hay versiones contradictorias',
  abstencion: 'Abstención: no hay evidencia suficiente',
};

export const COMPOSE_PROVIDER_LABEL: Record<ComposeProvider, string> = { gemini: 'Gemini', chatgpt: 'ChatGPT', claude: 'Claude' };
export const COMPOSE_PROVIDER_HELP: Record<ComposeProvider, string> = {
  gemini: 'Usa una llamada diaria gratuita de Gemini, dentro de su cuota.',
  chatgpt: 'Solo en este equipo; consume tu plan personal de ChatGPT.',
  claude: 'Solo en este equipo; consume tu suscripción de Claude.',
};

export const DATA_MODE_LABEL: Record<DataMode, string> = {
  fixture: 'Datos de fixture (no reales)',
  provisional: 'Snapshot provisional',
  congelado: 'Snapshot congelado',
};

export const FALLBACK_LABEL: Record<FallbackReason, string> = {
  contador_no_disponible: 'contador de cuota no disponible',
  limite_global: 'límite diario compartido alcanzado',
  modo_sin_conexion: 'modo sin conexión',
  cuota_agotada: 'cuota del proveedor agotada',
  limite_por_usuario: 'límite de borradores por usuario',
  proveedor_no_disponible: 'proveedor no disponible',
  proveedor_no_conectado: 'proveedor no conectado',
  sin_credenciales: 'sin credenciales del proveedor',
  validacion_fallida: 'la validación de citas falló',
  solo_localhost: 'conexión personal solo disponible en localhost',
  solicitado: 'solicitado por el usuario',
  sin_evidencia: 'no hay una respuesta con fuentes que redactar',
};

export const PROVIDER_CHOICES: { value: DraftProviderChoice; label: string; help: string }[] = [
  { value: 'auto', label: 'Automático', help: 'Gemini si hay cuota; si no, recuperado o plantilla.' },
  { value: 'gemini', label: 'Gemini (Free Tier)', help: 'Modelo gratuito dentro de su cuota.' },
  { value: 'recuperado', label: 'Recuperado', help: 'Reutiliza un borrador anterior guardado.' },
  { value: 'plantilla', label: 'Plantilla con citas', help: 'Sin modelo; funciona sin internet.' },
  { value: 'chatgpt', label: 'ChatGPT (solo localhost)', help: 'Conexión personal opcional.' },
  { value: 'claude', label: 'Claude (solo localhost)', help: 'Conexión personal opcional; consume créditos.' },
];

/** Claves de componentes de scoring-v1 (R, I, U, N, E) → nombre. */
export const COMPONENT_NAME: Record<string, string> = {
  R: 'Relevancia',
  I: 'Impacto',
  U: 'Urgencia',
  N: 'Novedad',
  E: 'Evidencia',
};
