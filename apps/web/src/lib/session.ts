import type { Route } from './router';

export type DemoRole = 'editor' | 'producer' | 'reviewer' | 'juror';
export type RoleAction =
  'impact' | 'rules' | 'createDraft' | 'editDraft' | 'review' | 'label' | 'importWorkspace';
export interface DemoSession {
  role: DemoRole;
  sessionId: string;
  labeler: string;
}
export const ROLES: { role: DemoRole; label: string; description: string }[] = [
  { role: 'editor', label: 'Editor/a', description: 'Agenda, impacto y decisiones editoriales' },
  { role: 'producer', label: 'Productor/a digital', description: 'Crear y editar paquetes para web y redes' },
  { role: 'reviewer', label: 'Revisor/a', description: 'Corregir, aprobar o descartar borradores' },
  { role: 'juror', label: 'Jurado', description: 'Recorrido completo, edición, métricas y etiquetado' },
];
const KEY = 'umbral.demoSession.v1';
const VIEWS: Record<DemoRole, readonly Route['view'][]> = {
  editor: ['agenda', 'ficha', 'fuentes', 'mesa', 'etiquetar'],
  producer: ['ficha', 'borradores', 'fuentes', 'etiquetar'],
  reviewer: ['ficha', 'borradores', 'fuentes', 'mesa', 'etiquetar'],
  juror: ['agenda', 'ficha', 'borradores', 'fuentes', 'mesa', 'etiquetar'],
};
const ACTIONS: Record<RoleAction, readonly DemoRole[]> = {
  impact: ['editor', 'juror'],
  rules: ['editor', 'juror'],
  createDraft: ['producer', 'juror'],
  editDraft: ['producer', 'reviewer', 'juror'],
  review: ['editor', 'reviewer', 'juror'],
  label: ['editor', 'producer', 'reviewer', 'juror'],
  importWorkspace: ['editor', 'juror'],
};
export function canView(role: DemoRole, view: Route['view']): boolean {
  return VIEWS[role].includes(view);
}
export function canPerform(role: DemoRole, action: RoleAction): boolean {
  return ACTIONS[action].includes(role);
}
export function defaultRoute(role: DemoRole): Route {
  return role === 'editor' || role === 'juror' ? { view: 'agenda' } : { view: 'ficha', topicId: null };
}
export function readSession(): DemoSession | null {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Partial<DemoSession> | null;
    const definition = ROLES.find((entry) => entry.role === value?.role);
    if (!definition || typeof value?.sessionId !== 'string' || !/^[0-9a-f-]{36}$/i.test(value.sessionId))
      return null;
    return { role: definition.role, sessionId: value.sessionId, labeler: definition.label };
  } catch {
    return null;
  }
}
export function chooseRole(role: DemoRole, previous: DemoSession | null): DemoSession {
  const session = {
    role,
    sessionId: previous?.sessionId ?? crypto.randomUUID(),
    labeler: ROLES.find((entry) => entry.role === role)!.label,
  };
  try {
    localStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    /* La sesión funciona en memoria; el trabajo exige almacenamiento disponible. */
  }
  return session;
}
