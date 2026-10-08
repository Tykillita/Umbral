import { useEffect, useRef, useState, type RefObject } from 'react';
import {
  deleteAssistantConversation, loadAssistantConversation, loadAssistantHistory, newAssistantId,
  saveAssistantConversation, setLastAssistantConversation, subscribeAssistantHistory,
  type AssistantChange, type AssistantConversation,
} from '../../lib/api/assistantHistory';

/**
 * Conversaciones del asistente: estado en memoria (fuente de verdad síncrona en `conversationsRef`), guardado en IndexedDB,
 * borrador con debounce y sincronización entre pestañas (recarga solo la conversación que cambió).
 */
export function useAssistantHistory({ namespace, busy }: { namespace: string; busy: RefObject<Map<string, AbortController>> }) {
  const [conversations, setConversations] = useState<AssistantConversation[]>([]);
  const conversationsRef = useRef(conversations);
  conversationsRef.current = conversations;
  const [activeId, setActiveId] = useState<string | null>(null);
  const activeIdRef = useRef(activeId);
  activeIdRef.current = activeId;
  const [loaded, setLoaded] = useState(false);
  const [persistent, setPersistent] = useState(true);
  const deletedIds = useRef(new Set<string>());
  const draftTimer = useRef<number | undefined>(undefined);
  const draftDirty = useRef<string | null>(null);

  const markSaved = (ok: boolean) => { if (!ok) setPersistent(false); };

  function replaceConversation(item: AssistantConversation, save = true) {
    if (deletedIds.current.has(item.id)) return;
    const next = [item, ...conversationsRef.current.filter((conversation) => conversation.id !== item.id)].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    conversationsRef.current = next;
    setConversations(next);
    if (save) void saveAssistantConversation(item).then(markSaved);
  }

  function patchConversation(id: string, updater: (item: AssistantConversation) => AssistantConversation, touch = true, save = true) {
    const item = conversationsRef.current.find((conversation) => conversation.id === id);
    if (!item || deletedIds.current.has(id)) return;
    const next = updater(item);
    replaceConversation({ ...next, updatedAt: touch ? new Date().toISOString() : next.updatedAt }, save);
  }

  function flushDraft() {
    window.clearTimeout(draftTimer.current);
    const id = draftDirty.current;
    draftDirty.current = null;
    if (!id || deletedIds.current.has(id)) return;
    const item = conversationsRef.current.find((conversation) => conversation.id === id);
    if (item) void saveAssistantConversation(item).then(markSaved);
  }

  /** Actualiza el borrador al instante y lo guarda 300 ms después de la última pulsación. */
  function changeDraft(id: string, value: string) {
    patchConversation(id, (conversation) => ({ ...conversation, draft: value }), true, false);
    draftDirty.current = id;
    window.clearTimeout(draftTimer.current);
    draftTimer.current = window.setTimeout(flushDraft, 300);
  }

  /** Cancela el guardado pendiente del borrador (p. ej. al enviarlo, porque la conversación se guarda completa). */
  function discardPendingDraft() {
    window.clearTimeout(draftTimer.current);
    draftDirty.current = null;
  }

  function createConversation(initialDraft: string, topicId: string | null, topicTitle: string): AssistantConversation {
    const at = new Date().toISOString();
    const item: AssistantConversation = {
      id: newAssistantId(), namespace, title: 'Nueva conversación', createdAt: at, updatedAt: at,
      draft: initialDraft, scopeTopicId: topicId, scopeTopicTitle: topicTitle, turns: [], scrollAnchor: null,
    };
    replaceConversation(item);
    setActiveId(item.id);
    void setLastAssistantConversation(namespace, item.id).then(markSaved);
    return item;
  }

  /** Activa una conversación existente; devuelve `false` si fue eliminada. */
  function activateConversation(id: string): boolean {
    if (deletedIds.current.has(id)) return false;
    setActiveId(id);
    void setLastAssistantConversation(namespace, id).then(markSaved);
    return true;
  }

  async function removeConversation(target: string) {
    deletedIds.current.add(target);
    busy.current.get(target)?.abort();
    const ok = await deleteAssistantConversation(namespace, target);
    setPersistent((value) => value && ok);
    const remaining = conversationsRef.current.filter((item) => item.id !== target);
    conversationsRef.current = remaining;
    setConversations(remaining);
    if (activeIdRef.current === target) {
      const next = remaining[0];
      setActiveId(next?.id ?? null);
      if (next) void setLastAssistantConversation(namespace, next.id);
    }
  }

  // Vuelca el borrador pendiente al ocultar o cerrar la página y al desmontar.
  useEffect(() => {
    const flush = () => flushDraft();
    const onVisibility = () => { if (document.visibilityState === 'hidden') flushDraft(); };
    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('pagehide', flush);
      document.removeEventListener('visibilitychange', onVisibility);
      flushDraft();
    };
  // Solo al desmontar: los ayudantes leen refs.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let current = true;
    void loadAssistantHistory(namespace).then((snapshot) => {
      if (!current) return;
      const recovered = snapshot.conversations.map((conversation) => ({
        ...conversation,
        turns: conversation.turns.map((turn) => turn.state === 'pending' ? { ...turn, state: 'interrupted' as const, error: undefined } : turn),
      }));
      conversationsRef.current = recovered;
      setConversations(recovered);
      setPersistent(snapshot.persistent);
      const last = recovered.find((conversation) => conversation.id === snapshot.lastConversationId) ?? recovered[0];
      if (last) {
        setActiveId(last.id);
        if (last.id !== snapshot.lastConversationId) void setLastAssistantConversation(namespace, last.id);
      }
      setLoaded(true);
      for (const item of recovered) {
        const before = snapshot.conversations.find((old) => old.id === item.id);
        if (item.turns.some((turn, index) => turn.state === 'interrupted' && before?.turns[index]?.state === 'pending')) void saveAssistantConversation(item);
      }
    });

    const fullReload = () => {
      void loadAssistantHistory(namespace).then((snapshot) => {
        if (!current) return;
        const nextIds = new Set(snapshot.conversations.map((item) => item.id));
        for (const old of conversationsRef.current) if (!nextIds.has(old.id)) deletedIds.current.add(old.id);
        conversationsRef.current = snapshot.conversations;
        setConversations(snapshot.conversations);
        setPersistent(snapshot.persistent);
        if (activeIdRef.current && !nextIds.has(activeIdRef.current)) setActiveId(snapshot.conversations[0]?.id ?? null);
      });
    };

    const unsubscribe = subscribeAssistantHistory(namespace, (change: AssistantChange) => {
      const id = change.id;
      if (!id || change.type === 'changed') { fullReload(); return; }
      if (change.type === 'deleted') {
        deletedIds.current.add(id);
        busy.current.get(id)?.abort();
        const remaining = conversationsRef.current.filter((item) => item.id !== id);
        conversationsRef.current = remaining;
        setConversations(remaining);
        if (activeIdRef.current === id) setActiveId(remaining[0]?.id ?? null);
        return;
      }
      // `saved`: se vuelve a leer solo esa conversación. Si aquí hay una consulta en curso o un borrador sin guardar, lo local manda.
      if (busy.current.has(id)) return;
      void loadAssistantConversation(namespace, id).then((item) => {
        if (!current || !item || deletedIds.current.has(id)) return;
        const local = conversationsRef.current.find((conversation) => conversation.id === id);
        const merged = draftDirty.current === id && local ? { ...item, draft: local.draft } : item;
        if (local && local.updatedAt === merged.updatedAt && local.turns.length === merged.turns.length) return;
        replaceConversation(merged, false);
      });
    });
    return () => { current = false; unsubscribe(); };
  // La identidad (API y sesión) es lo único que cambia el espacio; activeId no es un disparador de recarga.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace]);

  useEffect(() => {
    if (activeId) void setLastAssistantConversation(namespace, activeId).then(markSaved);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, namespace]);

  return {
    conversations, conversationsRef, activeId, activeIdRef, loaded, persistent, setPersistent, deletedIds,
    replaceConversation, patchConversation, changeDraft, flushDraft, discardPendingDraft,
    createConversation, activateConversation, removeConversation,
  };
}
