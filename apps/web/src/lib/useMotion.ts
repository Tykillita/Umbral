import { useCallback, useLayoutEffect, useRef, type RefObject } from 'react';
import { cancelMotion, playCards, playDisclosure, playHeading } from './motion';

const HEADING = '[data-motion="heading"]';
const CARD = '[data-motion="card"]';

/**
 * Entrada de una sección. `key` identifica sección y tema («ficha:tema-1»): al cambiar se repite sin remontar
 * nada, así que los formularios conservan sus ediciones. El encabezado entra al abrir la vista; las tarjetas
 * (`[data-motion="card"]`) cuando `cardsReady` indica que sus datos ya están. Buscar, filtrar o refrescar no
 * cambian la clave ni `cardsReady`, y el contenido permanece quieto.
 */
export function useEntrance(ref: RefObject<HTMLElement | null>, key: string, cardsReady = true): void {
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;
    const heads = [...root.querySelectorAll(HEADING)];
    for (const h of heads) playHeading(h);
    return () => heads.forEach((h) => cancelMotion(h));
  }, [ref, key]);

  useLayoutEffect(() => {
    const root = ref.current;
    if (!root || !cardsReady) return;
    const cards = [...root.querySelectorAll(CARD)];
    playCards(cards);
    return () => cards.forEach((c) => cancelMotion(c));
  }, [ref, key, cardsReady]);
}

/**
 * «Ver más»: anima únicamente las tarjetas que no estaban cuando se armó. `arm` se llama justo antes de
 * pedir más datos; `scopeKey` (filtros y búsqueda) lo desarma para que otros cambios de lista no animen.
 */
export function useRevealNew(ref: RefObject<HTMLElement | null>, ids: readonly string[], scopeKey: string): () => void {
  const baseline = useRef<Set<string> | null>(null);
  const current = useRef(ids);
  current.current = ids;

  useLayoutEffect(() => {
    baseline.current = null;
  }, [scopeKey]);

  const idsKey = ids.join('\n');
  useLayoutEffect(() => {
    const base = baseline.current;
    const root = ref.current;
    if (!base || !root || !ids.some((id) => !base.has(id))) return;
    baseline.current = null;
    const fresh = [...root.querySelectorAll<HTMLElement>(CARD)].filter((el) => el.dataset.motionId && !base.has(el.dataset.motionId));
    playCards(fresh);
    return () => fresh.forEach((c) => cancelMotion(c));
    // `ids` se resume en idsKey: el efecto solo depende de qué tarjetas hay.
  }, [ref, idsKey]);

  return useCallback(() => {
    baseline.current = new Set(current.current);
  }, []);
}

/** Despliegue breve al pasar de cerrado a abierto (no al montar ya abierto). El cierre es inmediato. */
export function useDisclosureMotion<T extends HTMLElement>(open: boolean): RefObject<T | null> {
  const ref = useRef<T>(null);
  const was = useRef(open);
  useLayoutEffect(() => {
    const el = ref.current;
    if (open && !was.current) playDisclosure(el);
    was.current = open;
    return () => cancelMotion(el);
  }, [open]);
  return ref;
}
