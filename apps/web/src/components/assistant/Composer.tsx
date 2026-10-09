import type { KeyboardEvent, RefObject } from 'react';
import { Send } from 'lucide-react';
import type { QueryContext } from '../../lib/api/types';
import type { SearchMode } from '../../lib/api/types';
import { Button, inputCls } from '../ui';
import { Checkbox, Select } from '../ui/controls';

export function Composer({
  latestContext, continueContext, onContinueChange, scopeOptions, scopeTopicId, scopeTitle, onScope,
  draft, onDraft, onKeyDown, inputRef, touch, charCount, running, onSubmit,
  searchMode, onSearchMode,
}: {
  latestContext: QueryContext | null;
  continueContext: boolean;
  onContinueChange: (value: boolean) => void;
  scopeOptions: Array<{ value: string; label: string }>;
  scopeTopicId: string | null;
  /** Título legible del ámbito elegido (vacío si el ámbito es toda la agenda). */
  scopeTitle: string;
  onScope: (value: string) => void;
  draft: string;
  onDraft: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  /** Teclado táctil: Enter añade una línea y se envía con el botón. */
  touch: boolean;
  charCount: number;
  running: boolean;
  onSubmit: () => void;
  searchMode: SearchMode;
  onSearchMode: (value: SearchMode) => void;
}) {
  const invalidLength = charCount < 3 || charCount > 500;
  return (
    <form noValidate className="assistant-composer" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
      {latestContext && (
        <div className="assistant-continue">
          <Checkbox checked={continueContext} onChange={onContinueChange} testId="assistant-continue">Continuar con el contexto de la respuesta anterior</Checkbox>
          <p className="assistant-input-help">Solo se envía el tema, país, indicador, años e identificadores de fuente de esa respuesta; nunca su texto ni el historial.</p>
        </div>
      )}
      <div className="assistant-scope-row">
        <label htmlFor="assistant-scope">Ámbito</label>
        <Select id="assistant-scope" value={scopeTopicId ?? 'agenda'} onChange={onScope} options={scopeOptions} label="Ámbito de consulta" testId="assistant-scope" />
      </div>
      <div className="assistant-scope-row">
        <label htmlFor="assistant-search-mode">Búsqueda</label>
        <Select id="assistant-search-mode" value={searchMode} onChange={(value) => onSearchMode(value as SearchMode)} options={[
          { value: 'auto', label: 'Automática según actualidad' },
          { value: 'live', label: 'Buscar fuera del snapshot ahora' },
          { value: 'snapshot', label: 'Solo el snapshot verificado' },
        ]} label="Origen de búsqueda" testId="assistant-search-mode" />
      </div>
      {scopeTopicId && <p className="assistant-scope-title">Ficha: {scopeTitle}</p>}
      <label htmlFor="assistant-input" className="sr-only">Tu pregunta</label>
      <textarea id="assistant-input" ref={inputRef} data-testid="assistant-input" rows={2} value={draft} onChange={(event) => onDraft(event.target.value)} onKeyDown={onKeyDown} placeholder="Ej.: ¿Qué falta verificar del tema de tránsito del Canal?" className={`${inputCls} assistant-textarea`} aria-describedby="assistant-input-help" />
      <div className="assistant-composer-footer">
        <p id="assistant-input-help" className="assistant-input-help">
          {touch ? 'Enter añade una línea · Consulta para enviar' : 'Enter envía · Mayús+Enter añade línea'}
          {charCount >= 450 && <span className={charCount > 500 ? 'text-bad' : ''}> · {charCount}/500</span>}
        </p>
        <Button type="submit" variant="primary" icon={Send} busy={running} data-testid="assistant-send" disabled={invalidLength || running}>Consultar</Button>
      </div>
      {charCount > 500 && <p role="alert" className="text-xs text-bad">La pregunta supera los 500 caracteres. Acórtala antes de enviarla.</p>}
      {charCount > 0 && charCount < 3 && <p className="text-xs text-ink-3">Escribe al menos 3 caracteres para consultar.</p>}
    </form>
  );
}
