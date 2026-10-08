import { RotateCcw, X } from 'lucide-react';
import type { ComposeProvider, QueryContext } from '../../lib/api/types';
import type { AssistantTurn } from '../../lib/api/assistantHistory';
import { Button, Notice } from '../ui';
import { ErrorBoundary } from '../ui/ErrorBoundary';
import { Answer } from './AnswerCard';

/** Una pregunta con su estado (pendiente, interrumpida, error o respuesta) y, si es la última, sus continuaciones. */
export function TurnView({ turn, isLast, running, composing, canCompose, composeProvider, busy, now, onCancel, onRetry, onEditQuestion, onCopy, onRelatedTitles, onNavigate, onFollowUp, onCompose }: {
  turn: AssistantTurn;
  isLast: boolean;
  /** Esta pregunta tiene una consulta en vuelo en este momento. */
  running: boolean;
  composing: boolean;
  canCompose: { ok: boolean; reason?: string | null };
  composeProvider: ComposeProvider;
  onCompose: () => void;
  /** Hay alguna consulta en vuelo en la conversación (bloquea reintentos y continuaciones). */
  busy: boolean;
  now: number;
  onCancel: () => void;
  onRetry: (waitSeconds?: number) => void;
  onEditQuestion: (question: string) => void;
  onCopy: (turn: AssistantTurn) => void;
  onRelatedTitles: (turnId: string, titles: Record<string, string>) => void;
  onNavigate: (topicId: string) => void;
  onFollowUp: (question: string, context: QueryContext | null) => void;
}) {
  const retryAt = turn.retryAvailableAt ? Date.parse(turn.retryAvailableAt) : null;
  const waiting = retryAt != null && Date.now() < retryAt;
  const suggestions = turn.result?.followUpSuggestions ?? [];
  return (
    <section data-testid="assistant-turn" data-turn-id={turn.id} className="assistant-turn">
      <p className="comic-question assistant-question">
        {turn.question}
        {turn.topicId && <span className="mt-1 block text-xs opacity-80">Ficha: {turn.topicTitle || 'tema guardado'}</span>}
      </p>
      {turn.state === 'pending' && (
        <div className="assistant-pending">
          <p role="status"><span className="assistant-spinner" aria-hidden="true" />Buscando evidencia{running ? '…' : ' (consulta pendiente)'}</p>
          {running && <Button variant="ghost" icon={X} onClick={onCancel} data-testid="assistant-cancel">Cancelar consulta</Button>}
        </div>
      )}
      {turn.state === 'interrupted' && (
        <Notice tone="warn" animate={false} testId="assistant-interrupted">
          <p>La consulta se interrumpió al recargar. Puedes reintentar esta pregunta con su ámbito original.</p>
          <Button variant="secondary" icon={RotateCcw} disabled={busy} onClick={() => onRetry()} data-testid="assistant-retry">Reintentar</Button>
        </Notice>
      )}
      {turn.state === 'error' && (
        <Notice tone="bad" role="alert" animate={false} testId="assistant-error">
          <p>{turn.error}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button variant="secondary" icon={RotateCcw} disabled={busy || waiting} onClick={() => onRetry(retryAt ? Math.max(0, Math.ceil((retryAt - Date.now()) / 1000)) : 0)} data-testid="assistant-retry">
              {waiting && retryAt ? `Reintentar en ${Math.max(0, Math.ceil((retryAt - now) / 1000))} s` : 'Reintentar'}
            </Button>
            <Button variant="ghost" onClick={() => onEditQuestion(turn.question)} data-testid="assistant-edit-question">Editar pregunta</Button>
          </div>
        </Notice>
      )}
      {turn.result && (
        <ErrorBoundary fallback={(reset) => (
          <Notice tone="warn" animate={false} testId="assistant-answer-broken">
            <p>No se pudo mostrar esta respuesta guardada. Puedes consultarla de nuevo o eliminarla del historial.</p>
            <Button variant="secondary" icon={RotateCcw} onClick={() => { reset(); onRetry(); }}>Consultar de nuevo</Button>
          </Notice>
        )}>
          <Answer turn={turn} composing={composing} canCompose={canCompose} composeProvider={composeProvider} onCompose={onCompose} onCancelCompose={onCancel} onCopy={onCopy} onRelatedTitles={(titles) => onRelatedTitles(turn.id, titles)} onNavigate={onNavigate} />
        </ErrorBoundary>
      )}
      {isLast && turn.state === 'complete' && suggestions.length > 0 && (
        <div className="assistant-followups" data-testid="assistant-followups">
          <p className="font-semibold">Seguir con</p>
          <ul>{suggestions.map((question) => (
            <li key={question}>
              <button type="button" className="assistant-suggestion" data-testid="assistant-followup" disabled={busy} onClick={() => onFollowUp(question, turn.result?.followUpContext ?? null)}>{question}</button>
            </li>
          ))}</ul>
        </div>
      )}
    </section>
  );
}
