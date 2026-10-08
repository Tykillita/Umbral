import type { RefObject } from 'react';
import { FileText, Trash2 } from 'lucide-react';
import { fmtDateTime } from '../../lib/format';
import type { AssistantConversation } from '../../lib/api/assistantHistory';
import { Button, inputCls } from '../ui';
import { Tooltip } from '../ui/controls';

export function HistoryView({ total, items, search, onSearch, searchRef, onOpen, onExport, onDelete }: {
  total: number;
  items: AssistantConversation[];
  search: string;
  onSearch: (value: string) => void;
  searchRef: RefObject<HTMLInputElement | null>;
  onOpen: (id: string) => void;
  onExport: (item: AssistantConversation) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <section className="assistant-history" aria-label="Historial de conversaciones">
      <label className="sr-only" htmlFor="assistant-history-search">Buscar en el historial</label>
      <input id="assistant-history-search" ref={searchRef} className={inputCls} value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Buscar conversaciones…" data-testid="assistant-history-search" />
      <ul className="assistant-history-list">
        {items.map((item) => (
          <li key={item.id} className="assistant-history-item">
            <button type="button" className="assistant-history-open" onClick={() => onOpen(item.id)}>
              <strong>{item.title}</strong>
              <span>{item.turns.length} {item.turns.length === 1 ? 'pregunta' : 'preguntas'} · {fmtDateTime(item.updatedAt)}</span>
              <small>{item.turns.at(-1)?.question ?? 'Borrador sin enviar'}</small>
            </button>
            <div className="assistant-history-actions">
              <Tooltip content="Exportar a Markdown"><Button variant="ghost" icon={FileText} iconOnly aria-label={`Exportar ${item.title}`} onClick={() => onExport(item)} /></Tooltip>
              <Tooltip content="Eliminar conversación"><Button variant="ghost" icon={Trash2} iconOnly aria-label={`Eliminar ${item.title}`} onClick={() => onDelete(item.id)} /></Tooltip>
            </div>
          </li>
        ))}
      </ul>
      {total === 0 && <p className="p-3 text-sm text-ink-3">Todavía no hay conversaciones guardadas.</p>}
      {total > 0 && items.length === 0 && <p className="p-3 text-sm text-ink-3">No hay conversaciones que coincidan.</p>}
    </section>
  );
}
