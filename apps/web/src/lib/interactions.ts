// Respuesta táctil global: pulsación en botones, enlaces de navegación y filas seleccionables, trazos de
// impacto en acciones principales y despliegue de <details>. Solo escucha: nunca llama a preventDefault,
// no retrasa el clic ni toca el estado de React, así que los formularios y las acciones siguen igual.
import { playBurst, playDisclosure, playPress } from './motion';

const PRESSABLE = 'button, a[href], summary, [role="button"]';

function pressHost(target: EventTarget | null): HTMLElement | null {
  const origin = target instanceof Element ? target : null;
  const el = origin?.closest<HTMLElement>(PRESSABLE);
  if (!el || el.matches(':disabled, [aria-disabled="true"], [data-no-press]') || el.closest('[inert]')) return null;
  const host = el.closest<HTMLElement>('[data-press-host]') ?? el;
  // Un enlace en línea no admite transformaciones: solo se anima si es un cuadro propio o tiene anfitrión.
  if (host === el && getComputedStyle(el).display === 'inline') return null;
  return host;
}

export function installInteractions(doc: Document = document): () => void {
  const onPointerDown = (e: PointerEvent) => {
    if (e.button !== 0 || e.isPrimary === false) return;
    playPress(pressHost(e.target));
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.repeat || e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    const el = e.target instanceof Element ? e.target.closest(PRESSABLE) : null;
    if (!el) return;
    const activates = el.tagName === 'A' || el.tagName === 'SUMMARY' ? e.key === 'Enter' : e.key === 'Enter' || e.key === ' ';
    if (activates) playPress(pressHost(e.target));
  };
  const onClick = (e: MouseEvent) => {
    const button = e.target instanceof Element ? e.target.closest('button') : null;
    if (!button || button.disabled) return;
    playBurst(button.querySelector('[data-ink]'));
  };
  // «toggle» no burbujea: se escucha en captura.
  const onToggle = (e: Event) => {
    const details = e.target;
    if (!(details instanceof HTMLDetailsElement) || !details.open) return;
    for (const child of details.children) if (child.tagName !== 'SUMMARY') playDisclosure(child);
  };

  doc.addEventListener('pointerdown', onPointerDown, true);
  doc.addEventListener('keydown', onKeyDown, true);
  doc.addEventListener('click', onClick, true);
  doc.addEventListener('toggle', onToggle, true);
  return () => {
    doc.removeEventListener('pointerdown', onPointerDown, true);
    doc.removeEventListener('keydown', onKeyDown, true);
    doc.removeEventListener('click', onClick, true);
    doc.removeEventListener('toggle', onToggle, true);
  };
}
