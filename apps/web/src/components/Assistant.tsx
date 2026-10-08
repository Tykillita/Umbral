import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Bot, CircleSlash, ExternalLink, GitCompare, Send, TriangleAlert, X } from 'lucide-react';
import type { AnswerStatus, QueryResponse } from '../lib/api/types';
import { ANSWER_LABEL } from '../lib/labels';
import { fmtDateTime } from '../lib/format';
import { describeError } from '../lib/api/client';
import { cancelMotion, playBubble, playNotice, playPanelIn, playPanelOut } from '../lib/motion';
import { useApp } from './context';
import { Button, Notice, Pill, inputCls, type Tone } from './ui';
import { Checkbox } from './ui/controls';
import { RichText } from './ui/RichText';

const STATUS_TONE: Record<AnswerStatus, Tone> = {
  respondida: 'ok',
  parcial: 'warn',
  contradiccion: 'bad',
  abstencion: 'neutral',
};

const SUGGESTIONS = [
  'Qué cinco temas merecen revisión para la agenda de Panamá',
  'Dame contexto económico oficial del tema con indicadores',
  'Qué falta verificar en los temas de prioridad alta',
  'Qué cifra exacta de visitantes llegó a Panamá este mes',
];

type Turn = { id: number; question: string; scopedTo: string | null; pending: boolean; result?: QueryResponse; error?: string };

function Answer({ r, id }: { r: QueryResponse; id: string }) {
  const { go } = useApp();
  const abst = r.answerStatus === 'abstencion';
  return (
    <div data-testid="assistant-answer" data-bubble-id={id} data-status={r.answerStatus} className="comic-answer space-y-2 text-sm">
      <Pill tone={STATUS_TONE[r.answerStatus]} icon={abst ? CircleSlash : r.answerStatus === 'contradiccion' ? GitCompare : Bot}>
        {ANSWER_LABEL[r.answerStatus]}
      </Pill>
      <RichText text={r.answer} testId="assistant-answer-text" className="text-[0.9375rem]" />

      {abst && (
        <Notice tone="neutral" icon={CircleSlash} title="Abstención" testId="assistant-abstention" animate={false}>
          <p>{r.abstentionReason ?? 'No hay evidencia suficiente en el corpus.'}</p>
          {r.missing.length > 0 && (
            <div data-testid="assistant-missing">
              <p className="mt-1 font-semibold">Qué información haría falta:</p>
              <ul className="list-disc pl-5">
                {r.missing.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </div>
          )}
        </Notice>
      )}

      {!abst && r.missing.length > 0 && (
        <div data-testid="assistant-missing">
          <p className="font-semibold">Falta verificar:</p>
          <ul className="list-disc pl-5">
            {r.missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      {r.contradictions.length > 0 && (
        <div data-testid="assistant-contradictions" className="space-y-1">
          {r.contradictions.map((k) => (
            <div key={k.id} className="rounded border border-bad/50 bg-bad-bg/40 p-2">
              <p className="flex items-center gap-1.5 font-semibold text-bad">
                <GitCompare size={14} aria-hidden="true" /> {k.description}
              </p>
              <ul className="mt-1 space-y-0.5">
                {k.versions.map((v) => (
                  <li key={v.evidenceId}>
                    «{v.statement}» <span className="text-xs text-ink-3">— {v.outlet}, {fmtDateTime(v.publishedAt)}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-xs">Pendiente: {k.pendingVerification}</p>
            </div>
          ))}
        </div>
      )}

      {r.citations.length > 0 && (
        <div>
          <p className="font-semibold">Fuentes usadas</p>
          <ul className="mt-1 space-y-1" data-testid="assistant-citations">
            {r.citations.map((c, i) => (
              <li key={`${c.evidenceId}-${c.field}-${i}`} className="text-xs">
                {c.url && /^https?:\/\//.test(c.url) ? (
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    data-testid="assistant-citation"
                    data-evidence-id={c.evidenceId}
                    className="inline-flex items-start gap-1 text-info underline underline-offset-2"
                  >
                    <span>{c.title ?? c.evidenceId}</span>
                    <ExternalLink size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                    <span className="sr-only">(se abre en otra pestaña)</span>
                  </a>
                ) : (
                  <span data-testid="assistant-citation" data-evidence-id={c.evidenceId}>
                    {c.title ?? c.evidenceId}
                  </span>
                )}
                <span className="ml-1 font-mono text-ink-3">
                  {c.evidenceId} · {c.field}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {r.relatedTopicIds.length > 0 && (
        <p className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-ink-3">Temas relacionados:</span>
          {r.relatedTopicIds.map((id) => (
            <button
              key={id}
              type="button"
              className="rounded border border-rule-strong bg-paper px-1.5 py-0.5 font-mono underline-offset-2 hover:border-amber-600 hover:underline"
              onClick={() => go({ view: 'ficha', topicId: id })}
              data-testid="assistant-related-topic"
              data-topic-id={id}
            >
              {id}
            </button>
          ))}
        </p>
      )}

      {r.warnings.length > 0 && (
        <ul className="space-y-0.5 text-xs text-warn">
          {r.warnings.map((w) => (
            <li key={w} className="flex gap-1">
              <TriangleAlert size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
              {w}
            </li>
          ))}
        </ul>
      )}
      <p className="text-[11px] text-ink-3">
        Recuperación: {r.retrieval.method} · cobertura de términos {Math.round(r.retrieval.coverage * 100)} % · {r.retrieval.tookMs.toFixed(0)} ms · snapshot {r.snapshotId}
      </p>
    </div>
  );
}

export function Assistant({ open, modal = false, onClose, seed }: { open: boolean; modal?: boolean; onClose: () => void; seed: { text: string; n: number } }) {
  const { api, route } = useApp();
  const [text, setText] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [scoped, setScoped] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const counter = useRef(0);
  // El panel sigue montado mientras dura su salida; la conversación vive en este componente y no se pierde.
  const [shown, setShown] = useState(open);
  if (open && !shown) setShown(true);
  const leaving = useRef(false);
  const seenBubbles = useRef(new Set<string>());
  const currentTopic = route.view === 'ficha' || route.view === 'borradores' ? route.topicId : null;

  useEffect(() => {
    if (seed.n > 0) setText(seed.text);
  }, [seed]);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    inputRef.current?.focus();
    return () => {
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [open]);

  useEffect(() => {
    if (!open || !modal) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previous; };
  }, [open, modal]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [turns]);

  // Entrada lateral al abrir y salida breve al cerrar. Reabrir durante la salida la cancela sin repetir la entrada.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    if (open) {
      cancelMotion(panel);
      if (!leaving.current) playPanelIn(panel);
      leaving.current = false;
      return;
    }
    const exit = playPanelOut(panel);
    if (!exit) {
      setShown(false);
      return;
    }
    leaving.current = true;
    let current = true;
    exit.finished.then(
      () => {
        if (!current) return;
        leaving.current = false;
        setShown(false);
      },
      () => {},
    );
    return () => {
      current = false;
    };
  }, [open]);

  // Cada pregunta y respuesta entra una sola vez; al reabrir el panel no se repiten las ya vistas.
  useLayoutEffect(() => {
    const log = logRef.current;
    if (!log) return;
    log.querySelectorAll<HTMLElement>('[data-bubble-id]').forEach((el) => {
      const id = el.dataset.bubbleId as string;
      if (seenBubbles.current.has(id)) return;
      seenBubbles.current.add(id);
      // Los errores entran de forma sobria; preguntas y respuestas, como globos.
      if (id.startsWith('e')) playNotice(el, 'bad');
      else playBubble(el, el.dataset.bubbleSide === 'right' ? 'right' : 'left');
    });
  }, [turns, shown]);

  const ask = useMutation({
    mutationFn: ({ question, topicId }: { question: string; topicId: string | null }) => api.query({ question, topicId }),
  });

  function submit(q: string) {
    const question = q.trim();
    if (question.length < 3 || ask.isPending) return;
    const id = ++counter.current;
    const topicId = scoped && currentTopic ? currentTopic : null;
    setTurns((t) => [...t, { id, question, scopedTo: topicId, pending: true }]);
    setText('');
    ask.mutate(
      { question, topicId },
      {
        onSuccess: (result) => setTurns((t) => t.map((x) => (x.id === id ? { ...x, pending: false, result } : x))),
        onError: (e) => setTurns((t) => t.map((x) => (x.id === id ? { ...x, pending: false, error: describeError(e) } : x))),
      },
    );
  }

  if (!open && !shown) return null;
  return (
    <aside
      ref={panelRef}
      id="assistant-panel"
      data-testid="assistant-panel"
      aria-label="Asistente de consultas"
      role={modal ? 'dialog' : undefined}
      aria-modal={modal || undefined}
      inert={!open}
      aria-hidden={!open || undefined}
      className="comic-dialogue fixed inset-y-0 right-0 z-40 flex w-full max-w-[26rem] flex-col bg-paper shadow-2xl"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          onClose();
        }
        if (e.key === 'Tab' && modal) {
          const items = panelRef.current?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]');
          const first = items?.[0];
          const last = items?.[items.length - 1];
          if (e.shiftKey && document.activeElement === first && last) {
            e.preventDefault(); last.focus();
          } else if (!e.shiftKey && document.activeElement === last && first) {
            e.preventDefault(); first.focus();
          }
        }
      }}
    >
      <div className="comic-dialogue-header flex items-center justify-between px-4 py-3">
        <div>
          <p className="kicker">Asistente integrado</p>
          <h2 className="font-display text-lg font-bold leading-tight">Consulta la evidencia</h2>
        </div>
        <Button variant="ghost" onClick={onClose} aria-label="Cerrar asistente" data-testid="assistant-close" icon={X} />
      </div>

      <div ref={logRef} className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
        {turns.length === 0 && (
          <div className="space-y-2 text-sm text-ink-2">
            <p>Pregunta en español. Cada respuesta enlaza las fuentes usadas; si no hay evidencia, se abstiene y dice qué falta.</p>
            <ul className="space-y-1.5">
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <button
                    type="button"
                    data-testid="assistant-suggestion"
                    className="min-h-11 w-full rounded-md border border-rule-strong bg-card px-3 py-2.5 text-left text-sm hover:border-amber-600 hover:bg-amber-50"
                    onClick={() => submit(s)}
                  >
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {turns.map((t) => (
          <div key={t.id} className="space-y-1.5" data-testid="assistant-turn">
            <p data-bubble-id={`q${t.id}`} data-bubble-side="right" className="comic-question ml-6 bg-ink px-3 py-2 text-sm text-white">
              {t.question}
              {t.scopedTo && <span className="mt-0.5 block text-xs opacity-80">Limitada al tema {t.scopedTo}</span>}
            </p>
            {t.pending && (
              <p role="status" className="text-sm text-ink-3">
                Buscando evidencia…
              </p>
            )}
            {t.error && (
              <Notice tone="bad" role="alert" testId="assistant-error" animate={false} data-bubble-id={`e${t.id}`}>
                {t.error}
              </Notice>
            )}
            {t.result && <Answer r={t.result} id={`a${t.id}`} />}
          </div>
        ))}
      </div>

      <form
        noValidate
        className="space-y-2 border-t border-rule bg-card p-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit(text);
        }}
      >
        {currentTopic && (
          <Checkbox checked={scoped} onChange={setScoped} testId="assistant-scope" className="text-xs text-ink-2">
            Limitar a la ficha abierta
          </Checkbox>
        )}
        <label htmlFor="assistant-input" className="sr-only">
          Tu pregunta
        </label>
        <textarea
          id="assistant-input"
          ref={inputRef}
          data-testid="assistant-input"
          rows={2}
          value={text}
          maxLength={600}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit(text);
            }
          }}
          placeholder="Ej.: ¿Qué falta verificar del tema de tránsito del Canal?"
          className={inputCls}
        />
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] text-ink-3"><span className="hidden sm:inline">Enter envía · Mayús+Enter salto de línea · Esc cierra</span><span className="sm:hidden">Toca «Consultar» para enviar</span></p>
          <Button type="submit" variant="primary" icon={Send} busy={ask.isPending} data-testid="assistant-send" disabled={text.trim().length < 3}>
            Consultar
          </Button>
        </div>
      </form>
    </aside>
  );
}
