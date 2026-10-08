import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { IDBFactory } from 'fake-indexeddb';
import {
  assistantTitle, deleteAssistantConversation, loadAssistantConversation, subscribeAssistantHistory, exportAssistantMarkdown, loadAssistantHistory, loadAssistantComposeProvider, saveAssistantComposeProvider, MAX_ASSISTANT_CONVERSATIONS,
  normalizeAssistantConversation, saveAssistantConversation, setLastAssistantConversation, turnToMarkdown,
  type AssistantConversation, type AssistantTurn,
} from './assistantHistory';

beforeAll(() => vi.stubGlobal('indexedDB', new IDBFactory()));
afterAll(() => vi.unstubAllGlobals());

function conversation(namespace: string, id: string): AssistantConversation {
  const at = '2026-10-07T12:00:00.000Z';
  return {
    id, namespace, title: 'Nueva conversación', createdAt: at, updatedAt: at, draft: 'Pregunta guardada',
    scopeTopicId: 'tema-1', scopeTopicTitle: 'Titular del tema', turns: [], scrollAnchor: null,
  };
}

describe('historial local del asistente', () => {
  it('separa los espacios por identidad, guarda borrador y ámbito, y conserva la última conversación', async () => {
    const namespace = `history-test-${crypto.randomUUID()}`;
    const item = conversation(namespace, 'conv-a');
    expect(await saveAssistantConversation(item)).toBe(true);
    expect(await setLastAssistantConversation(namespace, item.id)).toBe(true);
    const saved = await loadAssistantHistory(namespace);
    expect(saved.persistent).toBe(true);
    expect(saved.lastConversationId).toBe(item.id);
    expect(saved.conversations[0]).toMatchObject({ draft: item.draft, scopeTopicId: item.scopeTopicId, scopeTopicTitle: item.scopeTopicTitle });
    expect((await loadAssistantHistory(`${namespace}-otra-identidad`)).conversations).toEqual([]);
  });

  it('usa un tombstone transaccional para que una respuesta tardía no recree una conversación eliminada', async () => {
    const namespace = `history-delete-${crypto.randomUUID()}`;
    const item = conversation(namespace, 'conv-late');
    await saveAssistantConversation(item);
    await setLastAssistantConversation(namespace, item.id);
    expect(await deleteAssistantConversation(namespace, item.id)).toBe(true);
    expect((await loadAssistantHistory(namespace)).conversations).toEqual([]);
    expect(await saveAssistantConversation({ ...item, turns: [] })).toBe(false);
    expect((await loadAssistantHistory(namespace)).conversations).toEqual([]);
  });

  it('recuerda el proveedor por identidad y conserva esa preferencia al cambiar o borrar la conversación activa', async () => {
    const namespace = `compose-provider-${crypto.randomUUID()}`;
    const item = conversation(namespace, 'conv-provider');
    expect(await loadAssistantComposeProvider(namespace)).toBe('gemini');
    expect(await saveAssistantComposeProvider(namespace, 'claude')).toBe(true);
    expect(await setLastAssistantConversation(namespace, item.id)).toBe(true);
    expect(await loadAssistantComposeProvider(namespace)).toBe('claude');
    expect(await deleteAssistantConversation(namespace, item.id)).toBe(true);
    expect(await loadAssistantComposeProvider(namespace)).toBe('claude');
  });

  it('exporta una pregunta completa y da un título legible a partir de su texto', () => {
    const item = conversation('history-export', 'conv-export');
    item.title = assistantTitle('   ¿Qué   falta verificar en el Canal?   ');
    item.turns = [{ id: 'turn-1', question: '¿Qué falta verificar?', topicId: 'tema-1', topicTitle: 'Canal de Panamá', createdAt: item.createdAt, state: 'interrupted' }];
    const markdown = exportAssistantMarkdown(item);
    expect(item.title).toBe('¿Qué falta verificar en el Canal?');
    expect(markdown).toContain('# ¿Qué falta verificar en el Canal?');
    expect(markdown).toContain('Canal de Panamá');
    expect(markdown).toContain('Consulta interrumpida al recargar');
  });

  it('descarta registros ilegibles y degrada un resultado malformado a un error reintentable', () => {
    expect(normalizeAssistantConversation(null)).toBeNull();
    expect(normalizeAssistantConversation({ id: 'x' })).toBeNull();
    expect(normalizeAssistantConversation({ ...conversation('n', 'futuro'), schemaVersion: 99 })).toBeNull();
    const broken = { ...conversation('n', 'roto'), turns: [
      { id: 't1', question: '¿Algo?', topicId: null, createdAt: 'x', state: 'complete', result: { answer: 'sin forma' } },
      { id: 't2', question: 'estado raro', topicId: null, createdAt: 'x', state: 'inventado' },
    ] };
    const clean = normalizeAssistantConversation(broken)!;
    expect(clean.turns).toHaveLength(1);
    expect(clean.turns[0]).toMatchObject({ state: 'error', result: undefined });
    expect(clean.turns[0]!.error).toMatch(/Reintenta/);
  });

  it('conserva como máximo las conversaciones más recientes de cada espacio', async () => {
    const namespace = `history-cap-${crypto.randomUUID()}`;
    for (let index = 0; index < MAX_ASSISTANT_CONVERSATIONS + 3; index += 1) {
      const item = conversation(namespace, `conv-${index}`);
      item.updatedAt = new Date(Date.UTC(2026, 9, 7, 12, 0, index)).toISOString();
      await saveAssistantConversation(item);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
    const saved = await loadAssistantHistory(namespace);
    expect(saved.conversations).toHaveLength(MAX_ASSISTANT_CONVERSATIONS);
    expect(saved.conversations.some((item) => item.id === 'conv-0')).toBe(false);
    expect(saved.conversations[0]!.id).toBe(`conv-${MAX_ASSISTANT_CONVERSATIONS + 2}`);
  });

  it('copiar y exportar comparten serializador, con etiquetas legibles y el pasaje citado', () => {
    const turn: AssistantTurn = {
      id: 't', question: '¿Qué evidencia hay?', topicId: null, createdAt: 'x', state: 'complete',
      result: {
        queryId: 'q1', question: '¿Qué evidencia hay?', intent: 'busqueda', answerStatus: 'parcial', answer: 'Hay un titular.',
        abstentionReason: null, citations: [{ evidenceId: 'e1', field: 'title', passage: 'Titular literal', title: 'Fuente', url: 'https://example.org/a' }],
        hits: [], contradictions: [{ id: 'c', description: 'Cifras distintas', status: 'revision_pendiente', pendingVerification: 'Confirmar', versions: [{ evidenceId: 'e1', statement: '3 heridos', outlet: 'TVN', publishedAt: '2026-10-07T00:00:00Z' }] }],
        missing: ['Fuente primaria'], relatedTopicIds: [], warnings: [], snapshotId: 's1', rulesVersion: 'scoring-v1', dataMode: 'fixture',
        retrieval: { method: 'bm25+rapidfuzz', corpusSize: 1, tookMs: 1, matchedTerms: [], coverage: 1 },
      } as unknown as AssistantTurn['result'],
    };
    const copy = turnToMarkdown(turn);
    expect(copy).toContain('Estado: Respuesta parcial');
    expect(copy).toContain('«Titular literal»');
    expect(copy).toContain('«3 heridos» — TVN');
    const item = conversation('history-md', 'c-md');
    item.turns = [turn];
    const exported = exportAssistantMarkdown(item);
    expect(exported).toContain('## ¿Qué evidencia hay?');
    expect(exported).toContain('Estado: Respuesta parcial');
    expect(exported).toContain('«Titular literal»');
    expect(exported).not.toContain('### parcial');
  });

  it('recarga una sola conversación y no devuelve las eliminadas', async () => {
    const namespace = `history-one-${crypto.randomUUID()}`;
    await saveAssistantConversation({ ...conversation(namespace, 'uno'), draft: 'borrador uno' });
    await saveAssistantConversation(conversation(namespace, 'dos'));
    expect((await loadAssistantConversation(namespace, 'uno'))?.draft).toBe('borrador uno');
    expect(await loadAssistantConversation(namespace, 'no-existe')).toBeNull();
    await deleteAssistantConversation(namespace, 'dos');
    expect(await loadAssistantConversation(namespace, 'dos')).toBeNull();
  });

  it('avisa a otras pestañas con el id de la conversación y cae a recarga completa ante mensajes desconocidos', async () => {
    const namespace = `history-channel-${crypto.randomUUID()}`;
    const received: Array<{ type: string; id?: string }> = [];
    const unsubscribe = subscribeAssistantHistory(namespace, (change) => received.push(change));
    const peer = new BroadcastChannel(`umbral-assistant-history-v1:${namespace}`);
    peer.postMessage({ type: 'saved', id: 'conv-x' });
    peer.postMessage({ type: 'deleted', id: 'conv-y' });
    peer.postMessage({ type: 'saved' });
    peer.postMessage('texto inesperado');
    await new Promise((resolve) => setTimeout(resolve, 50));
    unsubscribe();
    peer.close();
    expect(received).toEqual([{ type: 'saved', id: 'conv-x' }, { type: 'deleted', id: 'conv-y' }, { type: 'changed' }, { type: 'changed' }]);
  });
});
