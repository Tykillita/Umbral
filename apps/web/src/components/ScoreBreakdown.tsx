import { Info } from 'lucide-react';
import { Tooltip } from './ui/controls';
import type { ScoreComponent } from '../lib/api/types';
import { COMPONENT_NAME } from '../lib/labels';
import { fmtNumber } from '../lib/format';

/** Componentes de P = 30R + 25I + 20U + 15N + 10E con regla, justificación y límites. */
export function ScoreBreakdown({
  components,
  variant,
  testIdPrefix,
}: {
  components: ScoreComponent[];
  variant: 'compact' | 'full';
  testIdPrefix: 'score-component' | 'card-score';
}) {
  if (variant === 'compact') {
    return (
      <ul className="comic-score-grid grid grid-cols-5 gap-1.5" aria-label="Componentes del puntaje">
        {components.map((c) => (
          <li
            key={c.key}
            data-testid={`${testIdPrefix}-${c.key}`}
            data-value={String(c.value)}
            data-points={String(c.points)}
            className="comic-score-cell border border-rule text-center"
          >
            <Tooltip
              block
              content={`${COMPONENT_NAME[c.key] ?? c.label} · peso ${c.weight}: ${c.rule}${c.limits.length ? ` Límites: ${c.limits.join(' ')}` : ' Sin límites declarados.'}`}
              className="comic-score-tooltip px-1.5 py-1"
            >
              <span className="comic-score-cell-content">
                <span className="comic-score-weight block text-[11px] font-bold tracking-wide text-ink-3">
                  {c.key} · {c.weight}
                </span>
                <span className="block text-sm font-bold tabular-nums">{fmtNumber(c.points, 1)}</span>
                <span
                  className="block h-1 rounded bg-sunk"
                  role="img"
                  aria-label={`${COMPONENT_NAME[c.key] ?? c.label}: valor normalizado ${fmtNumber(c.value, 2)} de 1`}
                >
                  <span className="block h-1 rounded bg-amber-600" style={{ width: `${Math.round(c.value * 100)}%` }} />
                </span>
                <span className="comic-score-limits text-warn" aria-hidden="true">
                  {c.limits.length > 0 ? <><Info size={10} /> {c.limits.length} límite{c.limits.length > 1 ? 's' : ''}</> : '—'}
                </span>
              </span>
            </Tooltip>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <ul className="divide-y divide-rule rounded-md border border-rule bg-card" aria-label="Componentes del puntaje">
      {components.map((c) => (
        <li
          key={c.key}
          data-testid={`${testIdPrefix}-${c.key}`}
          data-value={String(c.value)}
          data-points={String(c.points)}
          className="grid gap-x-4 gap-y-1 p-3 sm:grid-cols-[11rem_1fr]"
        >
          <div>
            <p className="font-display text-base font-bold">
              {c.key} · {COMPONENT_NAME[c.key] ?? c.label}
            </p>
            <p className="text-sm tabular-nums text-ink-2">
              peso {c.weight} × valor {fmtNumber(c.value, 2)} = <strong className="text-ink">{fmtNumber(c.points, 1)}</strong> pts
            </p>
            <span className="mt-1 block h-1.5 max-w-44 rounded bg-sunk" role="img" aria-label={`Valor normalizado ${fmtNumber(c.value, 2)} de 1`}>
              <span className="block h-1.5 rounded bg-amber-600" style={{ width: `${Math.round(c.value * 100)}%` }} />
            </span>
          </div>
          <div className="space-y-1 text-sm">
            <p>
              <span className="text-ink-3">Regla aplicada: </span>
              {c.rule}
            </p>
            <p>
              <span className="text-ink-3">Por qué: </span>
              {c.justification}
            </p>
            {c.limits.length > 0 ? (
              <ul className="mt-1 space-y-0.5 rounded border border-warn/50 bg-warn-bg px-2.5 py-1.5 text-warn" data-testid={`${testIdPrefix}-${c.key}-limits`}>
                {c.limits.map((l) => (
                  <li key={l} className="flex gap-1.5">
                    <Info size={14} className="mt-1 shrink-0" aria-hidden="true" />
                    <span>
                      <strong>Límite:</strong> {l}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-ink-3">Sin límites declarados para este componente.</p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
