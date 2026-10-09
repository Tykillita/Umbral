import { ClipboardCheck, Gavel, Newspaper, PenLine } from 'lucide-react';
import type { ReactNode } from 'react';
import { ROLES, type DemoRole } from '../lib/session';
import { Button, Card, Notice, SectionTitle } from './ui';

const ICONS = { editor: Newspaper, producer: PenLine, reviewer: ClipboardCheck, juror: Gavel };
export function SessionGate({
  onChoose,
  onCancel,
  status,
}: {
  onChoose: (role: DemoRole) => void;
  onCancel?: () => void;
  status?: ReactNode;
}) {
  return (
    <main className="comic-sheet mx-auto max-w-3xl space-y-5 px-4 py-10" data-testid="session-gate">
      <a className="comic-brand" href="/" aria-label="Umbral, inicio">
        Umbral<span className="text-amber-600">.</span>
      </a>
      <Card>
        <SectionTitle heading kicker="Acceso público · equipo editorial">
          ¿Con qué rol entras a la mesa?
        </SectionTitle>
        <p className="mb-4 text-sm text-ink-2">
          Elige tu recorrido. No hace falta contraseña; tu rol firma las decisiones y etiquetas de esta
          sesión.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {ROLES.map(({ role, label, description }) => {
            const Icon = ICONS[role];
            return (
              <button
                key={role}
                type="button"
                data-testid={`role-${role}`}
                className="comic-role-card"
                onClick={() => onChoose(role)}
              >
                <Icon size={26} aria-hidden="true" />
                <span>
                  <strong className="block font-display text-xl">{label}</strong>
                  <span className="block text-sm text-ink-2">{description}</span>
                </span>
              </button>
            );
          })}
        </div>
        {onCancel && (
          <Button className="mt-4" onClick={onCancel}>
            Mantener mi rol actual
          </Button>
        )}
      </Card>
      {status}
      <Notice tone="info" title="Qué se guarda y dónde">
        Borradores y pesos siguen en tu espacio actual. Las decisiones y etiquetas se conservan en este
        navegador y, cuando la mesa está configurada, se comparten con el equipo. El selector de roles es una
        demostración pública: no verifica la identidad ni protege permisos de servidor.
      </Notice>
    </main>
  );
}
