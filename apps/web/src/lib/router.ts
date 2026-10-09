import { useCallback, useEffect, useState } from 'react';

export type Route =
  | { view: 'agenda' }
  | { view: 'ficha'; topicId: string | null }
  | { view: 'borradores'; topicId: string | null }
  | { view: 'fuentes' }
  | { view: 'mesa' }
  | { view: 'etiquetar' };

export function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  const [view, id] = parts;
  switch (view) {
    case 'ficha':
      return { view: 'ficha', topicId: id ?? null };
    case 'borradores':
      return { view: 'borradores', topicId: id ?? null };
    case 'fuentes':
      return { view: 'fuentes' };
    case 'mesa':
      return { view: 'mesa' };
    case 'etiquetar':
      return { view: 'etiquetar' };
    default:
      return { view: 'agenda' };
  }
}

export function toHash(r: Route): string {
  switch (r.view) {
    case 'ficha':
      return r.topicId ? `#/ficha/${encodeURIComponent(r.topicId)}` : '#/ficha';
    case 'borradores':
      return r.topicId ? `#/borradores/${encodeURIComponent(r.topicId)}` : '#/borradores';
    case 'fuentes':
      return '#/fuentes';
    case 'mesa':
      return '#/mesa';
    case 'etiquetar':
      return '#/etiquetar';
    default:
      return '#/agenda';
  }
}

export function useRoute(): [Route, (r: Route) => void] {
  const [route, setRoute] = useState<Route>(() =>
    typeof window === 'undefined' ? { view: 'agenda' } : parseHash(window.location.hash),
  );
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash));
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  const go = useCallback((r: Route) => {
    window.location.hash = toHash(r);
  }, []);
  return [route, go];
}
