import { createContext, isValidElement, useContext, useState, useSyncExternalStore, type ComponentType, type ReactNode, type SVGProps } from 'react';
import { TriangleAlert } from 'lucide-react';
import { Modal } from './controls';

export type WarningIcon = ComponentType<SVGProps<SVGSVGElement> & { size?: number | string }>;

export interface WarningEntry {
  id: string;
  tone: 'warn' | 'amber';
  title?: ReactNode;
  children?: ReactNode;
  icon?: WarningIcon;
  role?: 'status' | 'alert';
  testId?: string;
}

interface WarningRegistry {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => WarningEntry[];
  register: (entry: WarningEntry) => void;
  unregister: (id: string) => void;
}

const WarningRegistryContext = createContext<WarningRegistry | null>(null);
const EMPTY_WARNINGS: WarningEntry[] = [];
const NO_SUBSCRIBE = () => () => undefined;
const GET_EMPTY_WARNINGS = () => EMPTY_WARNINGS;

function visibleText(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(visibleText).join(' ');
  if (isValidElement(node)) return visibleText((node.props as { children?: ReactNode }).children);
  return '';
}

function createWarningRegistry(): WarningRegistry {
  const entries = new Map<string, WarningEntry>();
  const signatures = new Map<string, string>();
  const listeners = new Set<() => void>();
  let snapshot: WarningEntry[] = [];
  const publish = () => {
    snapshot = [...entries.values()];
    listeners.forEach((listener) => listener());
  };
  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    register(entry) {
      const signature = `${entry.tone}|${visibleText(entry.title)}|${visibleText(entry.children)}|${entry.testId ?? ''}|${entry.role ?? ''}|${entry.icon?.name ?? ''}`;
      const changed = !entries.has(entry.id) || signatures.get(entry.id) !== signature;
      entries.set(entry.id, entry);
      signatures.set(entry.id, signature);
      if (changed) publish();
    },
    unregister(id) {
      if (!entries.delete(id)) return;
      signatures.delete(id);
      publish();
    },
  };
}

export function WarningCenterProvider({ children }: { children: ReactNode }) {
  const [registry] = useState(createWarningRegistry);
  return <WarningRegistryContext.Provider value={registry}>{children}</WarningRegistryContext.Provider>;
}

export function useWarningRegistry() {
  return useContext(WarningRegistryContext);
}

export function useWarnings() {
  const registry = useWarningRegistry();
  return useSyncExternalStore(
    registry?.subscribe ?? NO_SUBSCRIBE,
    registry?.getSnapshot ?? GET_EMPTY_WARNINGS,
    registry?.getSnapshot ?? GET_EMPTY_WARNINGS,
  );
}

export function WarningCenter({
  open,
  onOpenChange,
  layaActive,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  layaActive: boolean;
}) {
  const warnings = useWarnings();
  const count = warnings.length + (layaActive ? 1 : 0);
  const label = count === 1 ? 'Avisos y advertencias, 1 aviso' : `Avisos y advertencias, ${count} avisos`;

  return (
    <>
      <button
        type="button"
        className={`comic-button inline-flex min-h-11 items-center justify-center gap-1.5 border-2 px-2.5 ${count ? 'border-warn text-warn' : ''}`}
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="warning-center"
        onClick={() => onOpenChange(true)}
        data-testid="warning-center-toggle"
      >
        <TriangleAlert size={17} aria-hidden="true" />
        {count > 0 && <span className="text-xs font-bold tabular-nums" aria-hidden="true">{count}</span>}
        <span className="sr-only" role="status" aria-live="polite">{count ? `${count} avisos activos` : 'Sin avisos activos'}</span>
      </button>
      <Modal
        open={open}
        title="Avisos y advertencias"
        description="Revisa estos avisos antes de usar los datos o continuar el trabajo editorial."
        onClose={() => onOpenChange(false)}
        testId="warning-center"
      >
        <div className="space-y-3">
          {layaActive && (
            <section className="comic-notice flex gap-3 border border-warn/60 bg-warn-bg px-3.5 py-3 text-sm text-warn" data-testid="classification-warning">
              <TriangleAlert size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
              <div className="min-w-0">
                <p className="font-semibold">Clasificación automática de Laya</p>
                <p className="mt-0.5 text-ink-2">Laya puede asignar categorías erróneas y sus porcentajes no son confianza editorial: revisa categoría e impacto antes de usar el ranking.</p>
              </div>
            </section>
          )}
          {warnings.map((warning) => {
            const Icon = warning.icon ?? TriangleAlert;
            return (
              <section
                key={warning.id}
                className={`comic-notice flex gap-3 border px-3.5 py-3 text-sm ${warning.tone === 'amber' ? 'border-warn/60 bg-warn-bg text-warn' : 'border-warn/50 bg-warn-bg text-warn'}`}
                data-testid={warning.testId ? `warning-${warning.testId}` : 'warning-item'}
                role={warning.role}
              >
                <Icon size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
                <div className="min-w-0">
                  {warning.title && <p className="font-semibold">{warning.title}</p>}
                  {warning.children && <div className={warning.title ? 'mt-0.5 text-ink-2' : ''}>{warning.children}</div>}
                </div>
              </section>
            );
          })}
          {count === 0 && <p className="rounded border border-rule bg-card px-3 py-3 text-sm text-ink-2" data-testid="warning-center-empty">No hay advertencias activas.</p>}
        </div>
      </Modal>
    </>
  );
}
