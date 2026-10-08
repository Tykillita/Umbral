import { useLayoutEffect, useRef, type ComponentType, type ReactNode, type SVGProps } from 'react';
import {
  Ban,
  BadgeCheck,
  Bot,
  CircleAlert,
  CircleCheck,
  CircleDot,
  CircleX,
  Clock,
  FileText,
  Hourglass,
  Info,
  Loader,
  Stamp,
  TriangleAlert,
} from 'lucide-react';
import type { EvidenceStatus, GenerationMode, ReviewStatus, ScoreBand } from '../../lib/api/types';
import { BAND_SHORT, EVIDENCE_LABEL, GENERATION_LABEL, REVIEW_LABEL } from '../../lib/labels';
import { ApiError, describeError } from '../../lib/api/client';
import { Tooltip } from './controls';
import { cancelMotion, scheduleNotice } from '../../lib/motion';

type Icon = ComponentType<SVGProps<SVGSVGElement> & { size?: number | string }>;
export type Tone = 'neutral' | 'ok' | 'warn' | 'bad' | 'info' | 'amber';

const TONE: Record<Tone, string> = {
  neutral: 'bg-sunk text-ink-2 border-rule-strong',
  ok: 'bg-ok-bg text-ok border-ok/40',
  warn: 'bg-warn-bg text-warn border-amber-500/50',
  bad: 'bg-bad-bg text-bad border-bad/40',
  info: 'bg-info-bg text-info border-info/40',
  amber: 'bg-amber-100 text-amber-700 border-amber-500/60',
};

export function Pill({
  tone = 'neutral',
  icon: Ico,
  children,
  testId,
  title,
  ...rest
}: {
  tone?: Tone;
  icon?: Icon;
  children: ReactNode;
  testId?: string;
  title?: string;
} & Record<`data-${string}`, string | undefined>) {
  const pill = (
    <span
      data-testid={testId}
      {...rest}
      className={`comic-pill inline-flex max-w-full items-center gap-1.5 whitespace-normal border px-2.5 py-0.5 text-xs font-semibold ${TONE[tone]}`}
    >
      {Ico && <Ico size={14} className="shrink-0" aria-hidden="true" />}
      {children}
    </span>
  );
  return title ? <Tooltip content={title}>{pill}</Tooltip> : pill;
}

const EVIDENCE_TONE: Record<EvidenceStatus, { tone: Tone; icon: Icon }> = {
  insuficiente: { tone: 'bad', icon: CircleX },
  parcial: { tone: 'warn', icon: CircleAlert },
  suficiente: { tone: 'ok', icon: CircleCheck },
};

export function EvidencePill({ status, testId = 'topic-evidence-status' }: { status: EvidenceStatus; testId?: string }) {
  const t = EVIDENCE_TONE[status];
  return (
    <Pill tone={t.tone} icon={t.icon} testId={testId} data-status={status}>
      {EVIDENCE_LABEL[status]}
    </Pill>
  );
}

const BAND_TONE: Record<ScoreBand, { tone: Tone; icon: Icon }> = {
  alto: { tone: 'amber', icon: TriangleAlert },
  medio: { tone: 'neutral', icon: CircleDot },
  bajo: { tone: 'neutral', icon: Clock },
};

export function BandPill({ band }: { band: ScoreBand }) {
  const t = BAND_TONE[band];
  return (
    <Pill tone={t.tone} icon={t.icon} testId="topic-band" data-band={band}>
      Prioridad {BAND_SHORT[band].toLowerCase()}
    </Pill>
  );
}

const REVIEW_TONE: Record<ReviewStatus, { tone: Tone; icon: Icon }> = {
  nuevo: { tone: 'neutral', icon: CircleDot },
  en_revision: { tone: 'info', icon: Hourglass },
  requiere_evidencia: { tone: 'warn', icon: TriangleAlert },
  aprobado_como_borrador: { tone: 'ok', icon: BadgeCheck },
  descartado: { tone: 'neutral', icon: Ban },
};

export function ReviewPill({ status, testId }: { status: ReviewStatus; testId?: string }) {
  const t = REVIEW_TONE[status];
  return (
    <Pill tone={t.tone} icon={t.icon} testId={testId} data-status={status}>
      {REVIEW_LABEL[status]}
    </Pill>
  );
}

const GEN_ICON: Record<GenerationMode, { tone: Tone; icon: Icon }> = {
  modelo: { tone: 'info', icon: Bot },
  recuperado: { tone: 'neutral', icon: Stamp },
  plantilla: { tone: 'neutral', icon: FileText },
};

export function GenerationPill({ mode, label }: { mode: GenerationMode; label?: string }) {
  const t = GEN_ICON[mode];
  return (
    <Pill tone={t.tone} icon={t.icon} testId="draft-origin-label" data-mode={mode}>
      {label ?? GENERATION_LABEL[mode]}
    </Pill>
  );
}

/** Entrada del aviso: se anima al montarse salvo que su sección ya lo haga entrar (`animate={false}` lo desactiva). */
function useNoticeMotion<T extends HTMLElement>(tone: Tone, animate: boolean, stamp: boolean) {
  const ref = useRef<T>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !animate) return;
    const icon = stamp ? el.querySelector('[data-stamp]') : null;
    scheduleNotice(el, tone, icon);
    return () => {
      cancelMotion(el);
      cancelMotion(icon);
    };
    // Solo al montar: un cambio de tono posterior no repite la entrada.
  }, []);
  return ref;
}

export function Notice({
  tone = 'info',
  title,
  children,
  testId,
  icon,
  role,
  animate = true,
  stamp = false,
  ...rest
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  testId?: string;
  icon?: Icon;
  role?: 'status' | 'alert';
  /** `false` cuando el contenedor ya anima su entrada (globo del asistente, sección que aparece). */
  animate?: boolean;
  /** Confirmaciones de guardado: efecto de sello sobre el icono. */
  stamp?: boolean;
} & Record<`data-${string}`, string | undefined>) {
  const Ico: Icon = icon ?? (tone === 'bad' ? CircleX : tone === 'warn' || tone === 'amber' ? TriangleAlert : tone === 'ok' ? CircleCheck : Info);
  const ref = useNoticeMotion<HTMLDivElement>(tone, animate, stamp);
  return (
    <div
      ref={ref}
      data-testid={testId}
      role={role}
      {...rest}
      className={`comic-notice flex gap-3 border px-3.5 py-3 text-sm ${TONE[tone]}`}
    >
      <Ico size={18} className="mt-0.5 shrink-0" aria-hidden="true" {...(stamp ? { 'data-stamp': '' } : {})} />
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={title ? 'mt-0.5 text-ink-2' : ''}>{children}</div>}
      </div>
    </div>
  );
}

/** Confirmación breve junto a una acción (p. ej. «Impacto guardado»), con el mismo sello que `Notice`. */
export function SavedInline({ children, testId }: { children: ReactNode; testId?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const icon = el.querySelector('[data-stamp]');
    scheduleNotice(el, 'ok', icon);
    return () => {
      cancelMotion(el);
      cancelMotion(icon);
    };
  }, []);
  return (
    <span ref={ref} data-testid={testId} role="status" className="ml-3 inline-flex items-center gap-1.5 align-middle text-sm text-ok">
      <CircleCheck size={16} className="shrink-0" aria-hidden="true" data-stamp="" />
      {children}
    </span>
  );
}

export function Button({
  variant = 'secondary',
  icon: Ico,
  children,
  busy,
  className = '',
  ...rest
}: {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  icon?: Icon;
  busy?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement> & { 'data-testid'?: string }) {
  const styles = {
    primary: 'bg-ink text-white border-ink hover:bg-amber-700 hover:border-amber-700',
    secondary: 'bg-card text-ink border-rule-strong hover:bg-amber-50 hover:border-amber-600',
    ghost: 'bg-transparent text-ink-2 border-transparent hover:bg-sunk',
    danger: 'bg-card text-bad border-bad/50 hover:bg-bad-bg',
  }[variant];
  const lead = busy ? <Loader size={16} className="animate-spin" aria-hidden="true" /> : Ico ? <Ico size={16} aria-hidden="true" /> : null;
  return (
    <button
      type="button"
      {...rest}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
      className={`comic-button ${variant === 'ghost' ? 'comic-ghost' : ''} inline-flex min-h-10 items-center justify-center gap-2 border px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-55 ${styles} ${className}`}
    >
      {lead && (
        <span className="comic-icon-slot">
          {lead}
          {variant === 'primary' && Ico && <InkStrokes />}
        </span>
      )}
      {children}
    </button>
  );
}

/** Trazos de impacto a la izquierda y arriba del icono (nunca sobre la etiqueta). Los dispara `interactions.ts`. */
function InkStrokes() {
  return (
    <span className="comic-ink" data-ink aria-hidden="true">
      <svg viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" focusable="false">
        <path d="M14 1.5v3.5M4.5 4.5l2.6 2.6M1.5 14H5M4.5 23.5l2.6-2.6" />
      </svg>
    </span>
  );
}

export function Loading({ label = 'Cargando…' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-8 text-ink-3">
      <Loader size={18} className="animate-spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBox({ error, onRetry, testId = 'error-box' }: { error: unknown; onRetry?: () => void; testId?: string }) {
  const status = error instanceof ApiError ? error.status : null;
  return (
    <Notice tone="bad" title="No se pudo completar la operación" testId={testId} role="alert">
      <p>{describeError(error)}</p>
      {status !== null && status > 0 && <p className="mt-1 text-xs text-ink-3">HTTP {status}{error instanceof ApiError ? ` · ${error.code}` : ''}</p>}
      {onRetry && (
        <Button className="mt-2" onClick={onRetry} variant="secondary">
          Reintentar
        </Button>
      )}
    </Notice>
  );
}

export function SectionTitle({ kicker, children, id, aside, heading }: { kicker?: string; children: ReactNode; id?: string; aside?: ReactNode; heading?: boolean }) {
  return (
    <div data-motion={heading ? 'heading' : undefined} className="comic-section-title mb-3 flex flex-wrap items-end justify-between gap-2 pb-2">
      <div>
        {kicker && <p className="kicker">{kicker}</p>}
        <h2 id={id} className="font-display text-xl font-bold leading-tight">
          {children}
        </h2>
      </div>
      {aside}
    </div>
  );
}

export function Card({ children, className = '', ...rest }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLElement> & { 'data-testid'?: string }) {
  return (
    <section data-motion="card" {...rest} className={`comic-panel p-4 ${className}`}>
      {children}
    </section>
  );
}

export function KV({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap gap-x-2">
      <dt className="text-ink-3">{k}</dt>
      <dd className="font-medium">{children}</dd>
    </div>
  );
}

export function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <label id={`${htmlFor}-label`} htmlFor={htmlFor} className="block text-sm font-semibold" onClick={() => document.getElementById(htmlFor)?.focus()}>
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

export const inputCls =
  'comic-input w-full border border-rule-strong bg-card px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-amber-600';
