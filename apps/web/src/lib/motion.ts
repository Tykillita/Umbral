// Movimiento de cómic de la aplicación editorial: tiempos, curvas y reproductores sobre Web Animations API.
// Todo es decorativo: ningún reproductor retrasa una acción, cambia el DOM ni deja estilos al terminar
// (las animaciones usan `fill: backwards`/`forwards` solo mientras duran) y, con movimiento reducido o sin
// soporte del navegador, cada reproductor devuelve `null` y el contenido cambia al instante.
import {
  applyMotionPreference,
  getMotionPreference,
  persistMotionPreference,
  type MotionPreference,
} from './motionPreference';

export type { MotionPreference } from './motionPreference';
export { getMotionPreference } from './motionPreference';

export const MOTION = {
  easing: {
    out: 'cubic-bezier(.22, 1, .36, 1)',
    bounce: 'cubic-bezier(.34, 1.56, .64, 1)',
    in: 'cubic-bezier(.4, 0, 1, 1)',
  },
  /** Encabezado de sección o ficha. */
  // La compresión es horizontal: el alto de los botones del encabezado (zonas táctiles de 44 px) no cambia.
  heading: { duration: 260, offset: 14, squash: 0.97 },
  /** Tarjetas: 280 ms cada una, 40 ms entre ellas y la secuencia completa nunca pasa de 480 ms. */
  card: { duration: 280, stagger: 40, maxTotal: 480, offset: 12 },
  press: { duration: 160, scale: 0.97, shift: 2 },
  burst: { duration: 180 },
  disclosure: { duration: 180, offset: 6 },
  notice: { duration: 220, offset: 8, errorDuration: 160, errorOffset: 4 },
  stamp: { duration: 220 },
  /** En pantallas estrechas los desplazamientos se reducen. */
  compactFactor: 0.6,
  compactQuery: '(max-width: 639px)',
} as const;

type Slot = 'enter' | 'exit' | 'press' | 'burst' | 'stamp';

const running = new WeakMap<Element, Map<Slot, Animation>>();
const activeAnimations = new Set<Animation>();

function media(query: string): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches;
}

export const reducedMotion = () => {
  const preference = getMotionPreference();
  if (preference === 'reduced') return true;
  if (preference === 'full') return false;
  return media('(prefers-reduced-motion: reduce)');
};
const dist = (px: number) => Math.round(px * (media(MOTION.compactQuery) ? MOTION.compactFactor : 1) * 10) / 10;

function canPlay(el: Element): el is HTMLElement {
  return el.isConnected && typeof (el as HTMLElement).animate === 'function' && !reducedMotion();
}

/** Cancela cualquier animación propia en curso sobre el elemento (desmontaje, reapertura, nueva entrada). */
export function cancelMotion(el: Element | null | undefined, slot?: Slot): void {
  const slots = el ? running.get(el) : undefined;
  if (!slots) return;
  for (const [name, anim] of [...slots]) {
    if (slot && slot !== name) continue;
    slots.delete(name);
    anim.cancel();
  }
}

export function cancelAllMotion(): void {
  for (const animation of [...activeAnimations]) animation.cancel();
}

export async function setMotionPreference(preference: MotionPreference): Promise<void> {
  applyMotionPreference(preference);
  if (reducedMotion()) cancelAllMotion();
  await persistMotionPreference(preference);
}

function play(el: Element | null | undefined, slot: Slot, frames: Keyframe[], options: KeyframeAnimationOptions): Animation | null {
  if (!el || !canPlay(el)) return null;
  cancelMotion(el, slot);
  let anim: Animation;
  try {
    anim = el.animate(frames, options);
  } catch {
    return null;
  }
  const slots = running.get(el) ?? new Map<Slot, Animation>();
  slots.set(slot, anim);
  activeAnimations.add(anim);
  running.set(el, slots);
  const forget = () => {
    activeAnimations.delete(anim);
    if (slots.get(slot) === anim) slots.delete(slot);
  };
  anim.addEventListener('finish', forget);
  anim.addEventListener('cancel', forget);
  return anim;
}

// --------------------------------------------------------------------------- ventana de asentamiento

// Un aviso que aparece junto con su sección no se anima por su cuenta: la sección ya lo hace entrar.
let settleUntil = 0;
const now = () => (typeof performance === 'undefined' ? Date.now() : performance.now());
export function settle(ms: number): void {
  settleUntil = Math.max(settleUntil, now() + ms);
}
export const isSettling = () => now() < settleUntil;
/** Cierra la ventana (pruebas y cambios de vista inmediatos). */
export function endSettling(): void {
  settleUntil = 0;
}

// --------------------------------------------------------------------------- reproductores

export function playHeading(el: Element | null | undefined): Animation | null {
  const o = dist(MOTION.heading.offset);
  const base = { transformOrigin: '50% 0' };
  settle(MOTION.heading.duration);
  return play(
    el,
    'enter',
    [
      { ...base, opacity: 0, transform: `translateY(${-o}px) scaleX(${MOTION.heading.squash})` },
      { ...base, opacity: 1, transform: `translateY(${o * 0.15}px) scaleX(1.012)`, offset: 0.6 },
      { ...base, opacity: 1, transform: 'none' },
    ],
    { duration: MOTION.heading.duration, easing: MOTION.easing.out, fill: 'backwards' },
  );
}

/** Retardo entre tarjetas para que `n` tarjetas completen su entrada dentro de `maxTotal`. */
export function staggerStep(n: number): number {
  if (n <= 1) return 0;
  return Math.min(MOTION.card.stagger, (MOTION.card.maxTotal - MOTION.card.duration) / (n - 1));
}

export function playCards(els: Iterable<Element>): Animation[] {
  const list = [...els];
  const step = staggerStep(list.length);
  const o = dist(MOTION.card.offset);
  const out: Animation[] = [];
  list.forEach((el, i) => {
    const anim = play(
      el,
      'enter',
      [
        { opacity: 0, transform: `translateY(${o}px)` },
        { opacity: 1, transform: 'none' },
      ],
      { duration: MOTION.card.duration, delay: Math.round(i * step), easing: MOTION.easing.out, fill: 'backwards' },
    );
    if (anim) out.push(anim);
  });
  if (out.length) settle(MOTION.card.maxTotal);
  return out;
}

export function playPress(el: Element | null | undefined): Animation | null {
  const { scale, shift, duration } = MOTION.press;
  return play(
    el,
    'press',
    [{ transform: 'none' }, { transform: `translateY(${shift}px) scale(${scale})`, offset: 0.35 }, { transform: 'none' }],
    { duration, easing: MOTION.easing.out },
  );
}

/** Trazos de impacto junto al icono de una acción principal. */
export function playBurst(el: Element | null | undefined): Animation | null {
  return play(
    el,
    'burst',
    [
      { opacity: 0, transform: 'scale(.6)' },
      { opacity: 1, transform: 'scale(1)', offset: 0.4 },
      { opacity: 0, transform: 'scale(1.25)' },
    ],
    { duration: MOTION.burst.duration, easing: MOTION.easing.out },
  );
}

export function playDisclosure(el: Element | null | undefined): Animation | null {
  const o = dist(MOTION.disclosure.offset);
  return play(
    el,
    'enter',
    [
      { opacity: 0, transform: `translateY(${-o}px)`, clipPath: 'inset(0 0 100% 0)' },
      { opacity: 1, transform: 'none', clipPath: 'inset(0 0 0 0)' },
    ],
    { duration: MOTION.disclosure.duration, easing: MOTION.easing.out },
  );
}

export function playNotice(el: Element | null | undefined, tone: string): Animation | null {
  if (tone === 'bad') {
    // Los errores entran de forma corta y sobria: sin rebote ni escala.
    const o = dist(MOTION.notice.errorOffset);
    return play(
      el,
      'enter',
      [
        { opacity: 0, transform: `translateY(${-o}px)` },
        { opacity: 1, transform: 'none' },
      ],
      { duration: MOTION.notice.errorDuration, easing: MOTION.easing.out, fill: 'backwards' },
    );
  }
  const o = dist(MOTION.notice.offset);
  return play(
    el,
    'enter',
    [
      { opacity: 0, transform: `translateY(${-o}px) scale(.98)` },
      { opacity: 1, transform: `translateY(${o * 0.12}px) scale(1.005)`, offset: 0.7 },
      { opacity: 1, transform: 'none' },
    ],
    { duration: MOTION.notice.duration, easing: MOTION.easing.out, fill: 'backwards' },
  );
}

/** Sello sobre el icono de una confirmación de guardado. */
export function playStamp(el: Element | null | undefined): Animation | null {
  const base = { transformOrigin: '50% 50%', transformBox: 'fill-box' };
  return play(
    el,
    'stamp',
    [
      { ...base, opacity: 0, transform: 'scale(1.9) rotate(-14deg)' },
      { ...base, opacity: 1, transform: 'scale(.9) rotate(3deg)', offset: 0.6 },
      { ...base, opacity: 1, transform: 'none' },
    ],
    { duration: MOTION.stamp.duration, easing: MOTION.easing.out, fill: 'backwards' },
  );
}

/**
 * Entrada de un aviso o confirmación. La decisión se toma en una microtarea: los efectos de la sección
 * que lo contiene (que corren después de los de sus hijos) ya habrán abierto la ventana de asentamiento,
 * y todo ocurre antes de pintar, así que no hay parpadeo.
 */
export function scheduleNotice(el: Element, tone: string, stamp?: Element | null): void {
  queueMicrotask(() => {
    if (!el.isConnected || isSettling()) return;
    playNotice(el, tone);
    if (stamp) playStamp(stamp);
  });
}
