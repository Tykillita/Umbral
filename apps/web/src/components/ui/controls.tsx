// Controles propios de Umbral. REGLA DEL PROYECTO (CLAUDE.md / AGENTS.md): la interfaz no usa controles nativos del
// navegador ni del sistema (<select>, casillas, campos numéricos, <details>, tooltips por `title`, barras de
// desplazamiento por defecto…). Todo se dibuja con estos componentes y con el CSS de global.css.
// Cada control mantiene el teclado y los roles ARIA de su patrón (APG): combobox de selección única, casilla,
// spinbutton, divulgación y tooltip.
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, ChevronRight, Minus, Monitor, Pause, Play, Plus, X } from 'lucide-react';
import { getMotionPreference, setMotionPreference, type MotionPreference } from '../../lib/motion';

/** Apariencia común de los campos propios (misma que `inputCls` de ui/index.tsx; se repite para evitar una importación circular). */
const FIELD =
  'comic-input w-full border border-rule-strong bg-card px-3 py-2 text-sm text-ink focus:border-amber-600';

export function useMediaQuery(query: string): boolean {
  const supported = typeof window !== 'undefined' && typeof window.matchMedia === 'function';
  const [matches, setMatches] = useState(() => (supported ? window.matchMedia(query).matches : false));
  useEffect(() => {
    if (!supported) return;
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, [query, supported]);
  return matches;
}

// --------------------------------------------------------------------------------------------- Select

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;
  hint?: string;
  disabled?: boolean;
}

type PopoverPos = { left: number; width: number; maxHeight: number; top?: number; bottom?: number };

/** Menú desplegable propio (combobox de selección única). En pantallas estrechas se abre como hoja inferior. */
export function Select<T extends string>({
  id,
  value,
  onChange,
  options,
  label,
  labelledBy,
  placeholder = 'Selecciona…',
  disabled = false,
  testId,
  className = '',
  triggerIcon,
  triggerPrefix,
  iconOnly = false,
  popoverMinWidth = 0,
}: {
  id?: string;
  value: T | '';
  onChange: (value: T) => void;
  options: SelectOption<T>[];
  /** Nombre accesible si no hay una etiqueta visible enlazada con `${id}-label`. */
  label?: string;
  labelledBy?: string;
  placeholder?: string;
  disabled?: boolean;
  testId?: string;
  className?: string;
  /** Icono opcional del disparador; con `iconOnly` la opción elegida queda solo para lector de pantalla. */
  triggerIcon?: ReactNode;
  /** Texto breve visible antes del valor seleccionado. */
  triggerPrefix?: string;
  iconOnly?: boolean;
  /** Ancho mínimo en píxeles del menú de escritorio, independiente del disparador. */
  popoverMinWidth?: number;
}) {
  const autoId = useId();
  const baseId = id ?? autoId;
  const listId = `${baseId}-list`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [pos, setPos] = useState<PopoverPos | null>(null);
  const [sheetTitle, setSheetTitle] = useState('');
  const triggerRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const typed = useRef({ text: '', at: 0 });
  const sheet = useMediaQuery('(max-width: 639px)');
  const selectedIndex = options.findIndex((o) => o.value === value);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : null;

  const openList = () => {
    if (disabled || options.length === 0) return;
    setActive(Math.max(0, selectedIndex));
    setSheetTitle(label ?? document.getElementById(labelledBy ?? `${baseId}-label`)?.textContent?.trim() ?? 'Elige una opción');
    setOpen(true);
  };
  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  };
  const choose = (index: number) => {
    const option = options[index];
    if (!option || option.disabled) return;
    onChange(option.value);
    close();
  };

  const place = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const vh = window.innerHeight;
    const below = vh - r.bottom - 12;
    const above = r.top - 12;
    const useBelow = below >= 220 || below >= above;
    const maxHeight = Math.max(140, Math.min(320, useBelow ? below : above));
    const width = Math.min(Math.max(r.width, popoverMinWidth), Math.max(0, window.innerWidth - 16));
    const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
    setPos({ left, width, maxHeight, ...(useBelow ? { top: r.bottom + 4 } : { bottom: vh - r.top + 4 }) });
  }, [popoverMinWidth]);

  useLayoutEffect(() => {
    if (!open || sheet) return;
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open, sheet, place]);

  // Cierre al pulsar fuera del control y de su lista.
  useEffect(() => {
    if (!open) return;
    const down = (event: PointerEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || popRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener('pointerdown', down, true);
    return () => document.removeEventListener('pointerdown', down, true);
  }, [open]);

  // La hoja inferior bloquea el desplazamiento de la página mientras está abierta.
  useEffect(() => {
    if (!open || !sheet) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open, sheet]);

  // Mantiene visible la opción activa dentro de la lista, sin mover la página.
  useEffect(() => {
    if (!open) return;
    const list = listRef.current;
    const item = document.getElementById(`${listId}-opt-${active}`);
    if (!list || !item) return;
    if (item.offsetTop < list.scrollTop) list.scrollTop = item.offsetTop;
    else if (item.offsetTop + item.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = item.offsetTop + item.offsetHeight - list.clientHeight;
  }, [open, active, listId, pos]);

  const typeahead = (key: string) => {
    const now = Date.now();
    if (now - typed.current.at > 600) typed.current.text = '';
    typed.current.at = now;
    typed.current.text += key.toLowerCase();
    const text = typed.current.text;
    const start = text.length === 1 ? active + 1 : active;
    for (let step = 0; step < options.length; step += 1) {
      const index = (start + step) % options.length;
      if (options[index]?.label.toLowerCase().startsWith(text)) {
        setActive(index);
        return;
      }
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    const key = event.key;
    const printable = key.length === 1 && key !== ' ' && !event.ctrlKey && !event.metaKey && !event.altKey;
    if (!open) {
      if (key === 'ArrowDown' || key === 'ArrowUp' || key === 'Enter' || key === ' ') {
        event.preventDefault();
        openList();
      } else if (printable) {
        event.preventDefault();
        openList();
        typeahead(key);
      }
      return;
    }
    switch (key) {
      case 'ArrowDown':
        event.preventDefault();
        setActive((i) => Math.min(options.length - 1, i + 1));
        break;
      case 'ArrowUp':
        event.preventDefault();
        setActive((i) => Math.max(0, i - 1));
        break;
      case 'PageDown':
        event.preventDefault();
        setActive((i) => Math.min(options.length - 1, i + 5));
        break;
      case 'PageUp':
        event.preventDefault();
        setActive((i) => Math.max(0, i - 5));
        break;
      case 'Home':
        event.preventDefault();
        setActive(0);
        break;
      case 'End':
        event.preventDefault();
        setActive(options.length - 1);
        break;
      case 'Enter':
      case ' ':
        event.preventDefault();
        choose(active);
        break;
      case 'Escape':
        event.preventDefault();
        event.stopPropagation();
        close();
        break;
      case 'Tab':
        setOpen(false);
        break;
      default:
        if (printable) {
          event.preventDefault();
          typeahead(key);
        }
    }
  };

  const list = (
    <ul
      ref={listRef}
      id={listId}
      role="listbox"
      tabIndex={-1}
      aria-labelledby={labelledBy ?? `${baseId}-label`}
      className="select-list"
      style={sheet ? undefined : { maxHeight: pos?.maxHeight }}
    >
      {options.map((option, index) => (
        <li
          key={option.value}
          id={`${listId}-opt-${index}`}
          role="option"
          aria-selected={index === selectedIndex}
          aria-disabled={option.disabled || undefined}
          data-value={option.value}
          data-disabled={option.disabled ? 'true' : undefined}
          data-testid="select-option"
          data-active={index === active ? 'true' : undefined}
          className="select-option"
          onPointerEnter={(e) => {
            if (e.pointerType === 'mouse') setActive(index);
          }}
          onPointerDown={(e) => e.preventDefault()}
          onClick={() => choose(index)}
        >
          <span className="min-w-0">
            <span className="block">{option.label}</span>
            {option.hint && <span className="block text-xs font-normal text-ink-3">{option.hint}</span>}
          </span>
          {index === selectedIndex && <Check size={16} aria-hidden="true" className="shrink-0" />}
        </li>
      ))}
    </ul>
  );

  return (
    <>
      <div
        ref={triggerRef}
        id={baseId}
        role="combobox"
        tabIndex={disabled ? -1 : 0}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open ? `${listId}-opt-${active}` : undefined}
        aria-labelledby={label ? undefined : (labelledBy ?? `${baseId}-label`)}
        aria-label={label}
        aria-disabled={disabled || undefined}
        data-testid={testId}
        data-value={value}
        data-open={open ? 'true' : 'false'}
        className={`${FIELD} select-trigger ${disabled ? 'is-disabled' : ''} ${className}`}
        onClick={() => (open ? close(false) : openList())}
        onKeyDown={onKeyDown}
      >
        {triggerIcon && <span className="select-trigger-icon" aria-hidden="true">{triggerIcon}</span>}
        {triggerPrefix && <span className="select-trigger-prefix" aria-hidden="true">{triggerPrefix}</span>}
        <span className={`select-value ${selected ? '' : 'is-placeholder'} ${iconOnly ? 'sr-only' : ''}`}>{selected ? selected.label : placeholder}</span>
        <ChevronDown size={16} aria-hidden="true" className="select-chevron" />
      </div>
      {open &&
        createPortal(
          sheet ? (
            <div className="select-layer" data-testid="select-sheet">
              <div className="select-backdrop" aria-hidden="true" onPointerDown={() => close()} />
              <div ref={popRef} className="select-sheet">
                <div className="select-sheet-head">
                  <span className="kicker">{sheetTitle}</span>
                  <button type="button" aria-label="Cerrar la lista" className="select-sheet-close" onClick={() => close()}>
                    <X size={18} aria-hidden="true" />
                  </button>
                </div>
                {list}
              </div>
            </div>
          ) : (
            <div
              ref={popRef}
              className="select-popover"
              style={{ position: 'fixed', left: pos?.left, width: pos?.width, top: pos?.top, bottom: pos?.bottom, visibility: pos ? 'visible' : 'hidden' }}
            >
              {list}
            </div>
          ),
          document.body,
        )}
    </>
  );
}

// ------------------------------------------------------------------------------------------- Checkbox

/** Casilla propia (rol checkbox). Toda la fila es clicable y el botón mide 44 px. */
export function Checkbox({
  checked,
  onChange,
  children,
  id,
  testId,
  disabled = false,
  className = '',
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  id?: string;
  testId?: string;
  disabled?: boolean;
  className?: string;
}) {
  const autoId = useId();
  const labelId = `${id ?? autoId}-label`;
  return (
    <label className={`check-row ${disabled ? 'is-disabled' : ''} ${className}`}>
      <button
        type="button"
        role="checkbox"
        id={id}
        aria-checked={checked}
        aria-labelledby={labelId}
        disabled={disabled}
        data-testid={testId}
        data-checked={checked ? 'true' : 'false'}
        className="check-box"
        onClick={() => onChange(!checked)}
      >
        <span className="check-visual" aria-hidden="true">
          {checked && <Check size={14} strokeWidth={3.5} />}
        </span>
      </button>
      <span id={labelId} className="min-w-0 flex-1">
        {children}
      </span>
    </label>
  );
}

// ----------------------------------------------------------------------------------------- NumberField

/** Campo numérico propio con botones − y + (spinbutton). Solo admite dígitos; valida el rango el formulario. */
export function NumberField({
  id,
  value,
  onValueChange,
  min = 0,
  max = 100,
  step = 1,
  disabled = false,
  testId,
  label,
}: {
  id?: string;
  value: number;
  onValueChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  testId?: string;
  label?: string;
}) {
  const [text, setText] = useState(Number.isFinite(value) ? String(value) : '');
  useEffect(() => {
    const parsed = text === '' ? Number.NaN : Number(text);
    const same = Number.isNaN(parsed) ? Number.isNaN(value) : parsed === value;
    if (!same) setText(Number.isFinite(value) ? String(value) : '');
    // Solo reacciona a cambios externos del valor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const clamp = (n: number) => Math.min(max, Math.max(min, n));
  const commit = (n: number) => {
    setText(Number.isFinite(n) ? String(n) : '');
    onValueChange(n);
  };
  const bump = (direction: 1 | -1) => commit(clamp((Number.isFinite(value) ? value : min) + direction * step));

  return (
    <div className={`number-field ${disabled ? 'is-disabled' : ''}`}>
      <button type="button" tabIndex={-1} aria-label="Disminuir" disabled={disabled || (Number.isFinite(value) && value <= min)} className="number-step" onClick={() => bump(-1)}>
        <Minus size={16} aria-hidden="true" />
      </button>
      <input
        id={id}
        data-testid={testId}
        role="spinbutton"
        inputMode="numeric"
        autoComplete="off"
        aria-label={label}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={Number.isFinite(value) ? value : undefined}
        disabled={disabled}
        value={text}
        className={`${FIELD} number-input`}
        onChange={(e) => {
          const digits = e.target.value.replace(/\D/g, '');
          setText(digits);
          onValueChange(digits === '' ? Number.NaN : Number(digits));
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowUp') {
            e.preventDefault();
            bump(1);
          } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            bump(-1);
          } else if (e.key === 'Home') {
            e.preventDefault();
            commit(min);
          } else if (e.key === 'End') {
            e.preventDefault();
            commit(max);
          }
        }}
      />
      <button type="button" tabIndex={-1} aria-label="Aumentar" disabled={disabled || (Number.isFinite(value) && value >= max)} className="number-step" onClick={() => bump(1)}>
        <Plus size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

// ------------------------------------------------------------------------------------------- Disclosure

/** Desplegable propio (patrón de divulgación). Sustituye a <details>/<summary>. */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  testId,
  className = '',
  triggerClassName = '',
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  /** Si se pasa, el estado lo controla quien llama (p. ej. para abrir la zona desde un enlace interno). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  testId?: string;
  className?: string;
  triggerClassName?: string;
}) {
  const [innerOpen, setInnerOpen] = useState(defaultOpen);
  const open = controlledOpen ?? innerOpen;
  const setOpen = (next: boolean) => { setInnerOpen(next); onOpenChange?.(next); };
  const uid = useId();
  const triggerId = `${uid}-trigger`;
  const panelId = `${uid}-panel`;
  return (
    <div className={`disclosure ${className}`} data-testid={testId} data-open={open ? 'true' : 'false'}>
      <button type="button" id={triggerId} aria-expanded={open} aria-controls={panelId} className={`disclosure-trigger ${triggerClassName}`} onClick={() => setOpen(!open)}>
        <ChevronRight size={16} aria-hidden="true" className="disclosure-chevron" />
        <span className="min-w-0 flex-1">{summary}</span>
      </button>
      <div id={panelId} role="region" aria-labelledby={triggerId} hidden={!open} className="disclosure-panel">
        {children}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------------------------- Tooltip

type TipPos = { left: number; top?: number; bottom?: number };

/** Globo de ayuda propio (hover, foco y toque). Sustituye al atributo `title`. El texto también está para lectores de pantalla. */
export function Tooltip({ content, children, block = false, className = '' }: { content: ReactNode; children: ReactNode; block?: boolean; className?: string }) {
  const id = useId();
  const hostRef = useRef<HTMLSpanElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [show, setShow] = useState(false);
  const [pos, setPos] = useState<TipPos | null>(null);

  const open = (delay: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setShow(true), delay);
  };
  const hide = () => {
    window.clearTimeout(timer.current);
    setShow(false);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);

  useLayoutEffect(() => {
    if (!show) return;
    const el = hostRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const half = Math.min(160, window.innerWidth / 2 - 8);
    const left = Math.min(Math.max(r.left + r.width / 2, half + 8), window.innerWidth - half - 8);
    setPos(r.top > 90 ? { left, bottom: window.innerHeight - r.top + 8 } : { left, top: r.bottom + 8 });
    const dismiss = () => setShow(false);
    window.addEventListener('scroll', dismiss, true);
    window.addEventListener('resize', dismiss);
    return () => {
      window.removeEventListener('scroll', dismiss, true);
      window.removeEventListener('resize', dismiss);
    };
  }, [show]);

  return (
    <span
      ref={hostRef}
      aria-describedby={id}
      className={`${block ? 'block' : 'inline-flex'} max-w-full ${className}`}
      onPointerEnter={(e) => {
        if (e.pointerType === 'mouse') open(250);
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === 'mouse') hide();
      }}
      onPointerDown={(e) => {
        if (e.pointerType !== 'mouse') {
          if (show) hide();
          else {
            open(0);
            window.setTimeout(() => setShow(false), 3500);
          }
        }
      }}
      onFocusCapture={() => open(0)}
      onBlurCapture={hide}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          hide();
        }
      }}
    >
      {children}
      <span id={id} className="sr-only">
        {content}
      </span>
      {show &&
        createPortal(
          <div className="tooltip" aria-hidden="true" style={{ left: pos?.left, top: pos?.top, bottom: pos?.bottom, visibility: pos ? 'visible' : 'hidden' }}>
            {content}
          </div>,
          document.body,
        )}
    </span>
  );
}

const MOTION_OPTIONS: { value: MotionPreference; label: string; hint: string; icon: typeof Monitor }[] = [
  { value: 'system', label: 'Usar preferencia del sistema', hint: 'Seguir el ajuste de movimiento del dispositivo', icon: Monitor },
  { value: 'reduced', label: 'Activar movimiento reducido', hint: 'Reducir las animaciones en esta plataforma', icon: Pause },
  { value: 'full', label: 'Desactivar movimiento reducido', hint: 'Permitir todas las animaciones en esta plataforma', icon: Play },
];

/** Selector segmentado de movimiento. Sigue el patrón de radio APG sin controles nativos. */
export function MotionPreferenceSwitch() {
  const [preference, setPreference] = useState<MotionPreference>(() => getMotionPreference());
  const [saveError, setSaveError] = useState('');
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const choose = (next: MotionPreference) => {
    if (next === preference) return;
    setPreference(next);
    setSaveError('');
    void setMotionPreference(next).catch(() => setSaveError('No se pudo guardar esta preferencia; seguirá activa hasta cerrar la app.'));
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const currentIndex = MOTION_OPTIONS.findIndex((option) => option.value === preference);
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % MOTION_OPTIONS.length;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (currentIndex + MOTION_OPTIONS.length - 1) % MOTION_OPTIONS.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = MOTION_OPTIONS.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const next = MOTION_OPTIONS[nextIndex];
    refs.current[nextIndex]?.focus();
    if (next) choose(next.value);
  };

  return (
    <div className="motion-switch" data-testid="motion-preference-switch">
      <div role="radiogroup" aria-label="Movimiento reducido" className="motion-switch-options" onKeyDown={onKeyDown}>
        {MOTION_OPTIONS.map(({ value, label, hint, icon: Icon }, index) => (
          <Tooltip key={value} content={hint}>
            <button
              ref={(element) => { refs.current[index] = element; }}
              type="button"
              role="radio"
              aria-label={label}
              aria-checked={preference === value}
              tabIndex={preference === value ? 0 : -1}
              data-testid={`motion-option-${value}`}
              className="motion-switch-option"
              onClick={() => choose(value)}
            >
              <Icon size={18} aria-hidden="true" />
            </button>
          </Tooltip>
        ))}
      </div>
      <span role="status" aria-live="polite" className="sr-only">{saveError}</span>
    </div>
  );
}

/** Modal propio de Umbral. Evita el diálogo nativo y mantiene el foco dentro de la superficie abierta. */
export function Modal({
  open,
  title,
  description,
  children,
  onClose,
  testId,
}: {
  open: boolean;
  title: ReactNode;
  description?: string;
  children?: ReactNode;
  onClose: () => void;
  testId?: string;
}) {
  const id = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const titleId = `${id}-title`;

  useEffect(() => {
    if (!open) return;
    const active = document.activeElement;
    openerRef.current = active instanceof HTMLElement ? active : null;
    const previousBodyOverflow = document.body.style.overflow;
    const previousDocumentOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
    dialogRef.current?.querySelector<HTMLElement>('[data-modal-autofocus]')?.focus({ preventScroll: true });
    if (!dialogRef.current?.contains(document.activeElement)) dialogRef.current?.focus({ preventScroll: true });

    return () => {
      document.body.style.overflow = previousBodyOverflow;
      document.documentElement.style.overflow = previousDocumentOverflow;
      if (openerRef.current?.isConnected) openerRef.current.focus({ preventScroll: true });
    };
  }, [open]);

  if (!open || typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="comic-modal-layer"
      data-testid={testId ? `${testId}-layer` : undefined}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          event.preventDefault();
          onClose();
        }
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? `${id}-description` : undefined}
        tabIndex={-1}
        data-testid={testId}
        className="comic-panel comic-modal-panel"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            onClose();
            return;
          }
          if (event.key !== 'Tab') return;
          const items = dialogRef.current?.querySelectorAll<HTMLElement>(
            'a[href], button:not(:disabled), input:not(:disabled), textarea:not(:disabled), [role="combobox"][tabindex="0"], [tabindex="0"]',
          );
          const focusable = [...new Set(Array.from(items ?? []))].filter((item) => item.getAttribute('aria-hidden') !== 'true');
          const first = focusable[0];
          const last = focusable[focusable.length - 1];
          if (!first || !last) {
            event.preventDefault();
          } else if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.current?.contains(document.activeElement))) {
            event.preventDefault();
            first.focus();
          }
        }}
      >
        <header className="comic-dialogue-header flex items-center justify-between gap-3 px-4 py-3">
          <h2 id={titleId} className="font-display text-xl font-bold leading-tight">{title}</h2>
          <button
            type="button"
            className="comic-button comic-icon-button inline-flex items-center justify-center border-2 border-transparent bg-transparent text-ink-2 hover:bg-sunk"
            aria-label="Cerrar ventana"
            onClick={onClose}
            data-modal-autofocus=""
          >
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        <div className="comic-modal-content p-4">
          {description && <p id={`${id}-description`} className="mb-3 text-ink-2">{description}</p>}
          {children}
        </div>
      </section>
    </div>,
    document.body,
  );
}
