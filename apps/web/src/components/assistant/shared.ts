import { config } from '../../lib/config';
import type { AssistantConversation } from '../../lib/api/assistantHistory';

export type AssistantVisibility = 'closed' | 'minimized' | 'open';
export type AssistantSize = 'compact' | 'expanded';
export type Seed = { text: string; topicId: string | null; topicTitle: string; n: number };

export const AGENDA_SUGGESTIONS = [
  '¿Qué cinco temas merecen revisión para la agenda y por qué?',
  '¿Qué falta verificar en los temas de prioridad alta?',
  '¿Qué fuentes independientes respaldan los temas principales?',
];

export function apiNamespace(): string {
  if (!config.apiUrl) return 'default-api';
  try { const url = new URL(config.apiUrl, window.location.origin); return `${url.origin}${url.pathname}`; }
  catch { return 'configured-api'; }
}

export function readAssistantSize(): AssistantSize {
  try { return window.localStorage.getItem('umbral.assistant.size') === 'expanded' ? 'expanded' : 'compact'; }
  catch { return 'compact'; }
}

/** Minúsculas sin tildes, para comparar y buscar. */
export function foldText(value: string): string {
  return value.normalize('NFD').replace(/[̀-ͯ]/g, '').toLocaleLowerCase();
}

export function conversationText(item: AssistantConversation): string {
  return foldText([item.title, item.draft, ...item.turns.flatMap((turn) => [turn.question, turn.result?.answer ?? ''])].join(' '));
}

export function hasCoarsePointer(): boolean {
  try { return window.matchMedia?.('(pointer: coarse)').matches ?? false; } catch { return false; }
}

export function unreadCount(conversations: AssistantConversation[]): number {
  return conversations.reduce((total, item) => total + item.turns.filter((turn) => turn.unread).length, 0);
}
