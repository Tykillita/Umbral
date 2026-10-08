import { useEffect, useState, type RefObject } from 'react';
import { ApiError, describeError } from '../../lib/api/client';
import { assistantTitle, type AssistantConversation } from '../../lib/api/assistantHistory';
import type { ComposeProvider } from '../../lib/api/types';
import { ANSWER_LABEL, FALLBACK_LABEL } from '../../lib/labels';
import type { useApp } from '../context';

type Api = ReturnType<typeof useApp>['api'];

type History = {
  conversationsRef: RefObject<AssistantConversation[]>;
  deletedIds: RefObject<Set<string>>;
  patchConversation: (id: string, updater: (item: AssistantConversation) => AssistantConversation, touch?: boolean, save?: boolean) => void;
};

/**
 * Ejecuta, cancela y reintenta consultas. Hay como mucho una consulta en vuelo por conversación (`inFlight`, compartido con el
 * historial para que una recarga desde otra pestaña no pise lo que está en curso).
 */
export function useAssistantQuery({ api, history, inFlight, isViewing, onViewedAnswer }: {
  api: Api;
  history: History;
  inFlight: RefObject<Map<string, AbortController>>;
  /** ¿La persona está mirando ahora mismo esta conversación? Si no, la respuesta queda marcada como no leída. */
  isViewing: (conversationId: string) => boolean;
  /** Llegó una respuesta a la conversación que se está mirando. */
  onViewedAnswer: () => void;
}) {
  const [runningIds, setRunningIds] = useState<string[]>([]);
  const [composingIds, setComposingIds] = useState<string[]>([]);
  const [announcement, setAnnouncement] = useState('');
  const { conversationsRef, deletedIds, patchConversation } = history;

  useEffect(() => () => { for (const controller of inFlight.current.values()) controller.abort(); }, [inFlight]);

  async function runTurn(conversationId: string, turnId: string, waitSeconds = 0) {
    if (inFlight.current.has(conversationId) || deletedIds.current.has(conversationId)) return;
    const turn = conversationsRef.current.find((item) => item.id === conversationId)?.turns.find((item) => item.id === turnId);
    if (!turn) return;
    const controller = new AbortController();
    inFlight.current.set(conversationId, controller);
    setRunningIds((ids) => [...ids, turnId]);
    patchConversation(conversationId, (item) => ({ ...item, turns: item.turns.map((entry) => entry.id === turnId ? { ...entry, state: 'pending', error: undefined } : entry) }));
    try {
      if (waitSeconds > 0) {
        await new Promise<void>((resolve) => {
          const timer = window.setTimeout(resolve, waitSeconds * 1000);
          controller.signal.addEventListener('abort', () => { window.clearTimeout(timer); resolve(); }, { once: true });
        });
      }
      if (controller.signal.aborted) throw new DOMException('Consulta cancelada', 'AbortError');
      // No se envían turnos anteriores ni textos: solo la pregunta, su ámbito y, si la conversación continúa, el contexto estructurado.
      const result = await api.query(
        turn.followUp ? { question: turn.question, topicId: turn.topicId, followUp: turn.followUp } : { question: turn.question, topicId: turn.topicId },
        { signal: controller.signal },
      );
      if (deletedIds.current.has(conversationId)) return;
      const viewing = isViewing(conversationId);
      patchConversation(conversationId, (item) => ({
        ...item,
        title: item.title === 'Nueva conversación' ? assistantTitle(turn.question) : item.title,
        turns: item.turns.map((entry) => entry.id === turnId ? { ...entry, state: 'complete', error: undefined, result, unread: !viewing } : entry),
      }));
      setAnnouncement(`Respuesta lista: ${ANSWER_LABEL[result.answerStatus]}.`);
      if (viewing) onViewedAnswer();
    } catch (error) {
      if (deletedIds.current.has(conversationId)) return;
      if (controller.signal.aborted) {
        patchConversation(conversationId, (item) => ({ ...item, turns: item.turns.map((entry) => entry.id === turnId ? { ...entry, state: 'error', error: 'Consulta cancelada. Puedes reintentarla o editar la pregunta.', retryAfter: null, retryAvailableAt: null } : entry) }));
        setAnnouncement('Consulta cancelada.');
        return;
      }
      const retryAfter = error instanceof ApiError ? error.retryAfter : null;
      const retryAvailableAt = retryAfter ? new Date(Date.now() + retryAfter * 1000).toISOString() : null;
      const message = describeError(error);
      patchConversation(conversationId, (item) => ({ ...item, turns: item.turns.map((entry) => entry.id === turnId ? { ...entry, state: 'error', error: message, retryAfter, retryAvailableAt } : entry) }));
      setAnnouncement(`No se pudo completar la consulta. ${message}`);
    } finally {
      if (inFlight.current.get(conversationId) === controller) inFlight.current.delete(conversationId);
      setRunningIds((ids) => ids.filter((id) => id !== turnId));
    }
  }

  /** Redacta con IA una respuesta ya recibida. Si el modelo falla o no pasa la validación, se conserva la de reglas con el motivo. */
  async function composeTurn(conversationId: string, turnId: string, provider: ComposeProvider = 'gemini') {
    if (inFlight.current.has(conversationId) || deletedIds.current.has(conversationId)) return;
    const turn = conversationsRef.current.find((item) => item.id === conversationId)?.turns.find((item) => item.id === turnId);
    if (!turn?.result) return;
    const controller = new AbortController();
    inFlight.current.set(conversationId, controller);
    setComposingIds((ids) => [...ids, turnId]);
    const note = (text: string | undefined) => patchConversation(conversationId, (item) => ({ ...item, turns: item.turns.map((entry) => entry.id === turnId ? { ...entry, composeNote: text } : entry) }), false);
    note(undefined);
    try {
      const body = turn.followUp
        ? { question: turn.question, topicId: turn.topicId, followUp: turn.followUp, provider }
        : { question: turn.question, topicId: turn.topicId, provider };
      const data = await api.compose(body, { signal: controller.signal });
      if (deletedIds.current.has(conversationId)) return;
      if (data.answerMode === 'modelo' && data.response.snapshotId === turn.result.snapshotId) {
        patchConversation(conversationId, (item) => ({
          ...item,
          turns: item.turns.map((entry) => entry.id === turnId
            ? { ...entry, result: data.response, answerMode: 'modelo', rulesAnswer: data.rulesAnswer, composedBy: data.model ?? data.provider ?? 'modelo', composeNote: undefined }
            : entry),
        }));
        setAnnouncement('Respuesta redactada con IA y verificada contra las fuentes.');
      } else {
        const reason = data.answerMode === 'modelo' ? 'los datos cambiaron desde que se hizo la pregunta; vuelve a preguntar' : `${data.fallbackReason ? FALLBACK_LABEL[data.fallbackReason] : 'sin motivo'}${data.fallbackDetail ? `: ${data.fallbackDetail}` : ''}`;
        note(reason);
        setAnnouncement(`No se redactó con IA. ${reason}`);
      }
    } catch (error) {
      if (deletedIds.current.has(conversationId)) return;
      const message = controller.signal.aborted ? 'redacción cancelada' : describeError(error);
      note(message);
      setAnnouncement(`No se redactó con IA. ${message}`);
    } finally {
      if (inFlight.current.get(conversationId) === controller) inFlight.current.delete(conversationId);
      setComposingIds((ids) => ids.filter((id) => id !== turnId));
    }
  }

  function cancelTurn(conversationId: string) {
    inFlight.current.get(conversationId)?.abort();
  }

  return { runTurn, composeTurn, cancelTurn, runningIds, composingIds, announcement };
}
