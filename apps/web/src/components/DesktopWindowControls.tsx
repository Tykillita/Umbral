import { useEffect, useLayoutEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import type { DesktopWindowControls } from '../lib/desktop';
import { Tooltip } from './ui/controls';

const ICONS = {
  minimize: 'M4 14h12',
  maximize: 'M4.5 4.5h11v11h-11z',
  restore: 'M7.5 7.5h8v8h-8zM7.5 4.5h8M4.5 7.5v8',
  close: 'M4.5 4.5l11 11M15.5 4.5l-11 11',
};

function Glyph({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true" focusable="false" className="desktop-wc-glyph">
      <path d={path} />
    </svg>
  );
}

function controls(): DesktopWindowControls | undefined {
  return typeof window !== 'undefined' ? window.umbralDesktop?.windowControls : undefined;
}

/**
 * Controles de ventana de la app de escritorio (la ventana no tiene marco nativo). La cabecera de la propia app
 * (`.comic-masthead`) hace de barra de título: es zona de arrastre y estos tres botones cuelgan de la esquina superior
 * derecha. Aquí se mide su altura para que el contenido haga scroll por debajo, con la cabecera fija y a todo el ancho.
 * No pinta nada en el navegador.
 */
export default function DesktopWindowControlsBar() {
  const api = controls();
  const [maximized, setMaximized] = useState(false);
  const [hasHeader, setHasHeader] = useState(false);

  useLayoutEffect(() => {
    if (!api) return;
    const root = document.documentElement;
    root.classList.add('desktop-shell');
    return () => {
      root.classList.remove('desktop-shell');
      root.style.removeProperty('--titlebar-h');
    };
  }, [api]);

  useEffect(() => {
    if (!api) return;
    const root = document.documentElement;
    let header: Element | null = null;
    let resize: ResizeObserver | undefined;
    const measure = () => {
      if (header) root.style.setProperty('--titlebar-h', `${Math.ceil(header.getBoundingClientRect().height)}px`);
    };
    const attach = () => {
      const next = document.querySelector('.comic-masthead');
      if (next === header) return;
      resize?.disconnect();
      header = next;
      setHasHeader(Boolean(header));
      if (header) {
        resize = new ResizeObserver(measure);
        resize.observe(header);
        measure();
      } else {
        root.style.removeProperty('--titlebar-h');
      }
    };
    attach();
    const mutations = new MutationObserver(attach);
    mutations.observe(document.body, { childList: true, subtree: true });
    return () => {
      mutations.disconnect();
      resize?.disconnect();
    };
  }, [api]);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    api.getState().then((s) => alive && setMaximized(s.maximized)).catch(() => {});
    const off = api.onStateChange((s) => setMaximized(s.maximized));
    return () => { alive = false; off(); };
  }, [api]);

  if (!api) return null;
  const toggleLabel = maximized ? 'Restaurar la ventana' : 'Maximizar la ventana';
  // Las zonas de arrastre de Chromium se resuelven por orden en el DOM (la última gana): los controles se montan al final
  // del <body> para que su «no-drag» prevalezca sobre el arrastre de la cabecera, que está debajo.
  return createPortal(
    <>
      {/* Sin cabecera (arranque o error) no habría por dónde arrastrar la ventana. */}
      {!hasHeader && <div className="desktop-drag-strip no-print" aria-hidden="true" />}
      <div className="desktop-wc-group no-print" role="group" aria-label="Controles de la ventana" data-testid="desktop-window-controls">
        <Tooltip content="Minimizar">
          <button type="button" className="desktop-wc" aria-label="Minimizar la ventana" data-testid="window-minimize" onClick={() => void api.minimize()}>
            <Glyph path={ICONS.minimize} />
          </button>
        </Tooltip>
        <Tooltip content={maximized ? 'Restaurar' : 'Maximizar'}>
          <button type="button" className="desktop-wc" aria-label={toggleLabel} data-testid="window-maximize" onClick={() => void api.toggleMaximize().then((s) => setMaximized(s.maximized))}>
            <Glyph path={maximized ? ICONS.restore : ICONS.maximize} />
          </button>
        </Tooltip>
        <Tooltip content="Cerrar Umbral">
          <button type="button" className="desktop-wc desktop-wc-close" aria-label="Cerrar Umbral" data-testid="window-close" onClick={() => void api.close()}>
            <Glyph path={ICONS.close} />
          </button>
        </Tooltip>
      </div>
    </>,
    document.body,
  );
}
