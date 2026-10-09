// Movimiento de cómic: jsdom no implementa Web Animations API, así que se simula con un registro de llamadas.
// Se comprueba la coreografía (qué se anima, cuándo y cuántas veces) y que ninguna animación altera el comportamiento.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { Bot } from 'lucide-react';
import type { Route } from './router';
import { MockApi } from './mock/mockApi';
import { MOTION, cancelAllMotion, endSettling, playCards, playHeading, reducedMotion, setMotionPreference, settle, staggerStep } from './motion';
import { MOTION_PREFERENCE_STORAGE_KEY } from './motionPreference';
import { installInteractions } from './interactions';
import { AppContext } from '../components/context';
import { MotionPreferenceSwitch } from '../components/ui/controls';
import { Agenda } from '../components/views/Agenda';
import { Button, Notice } from '../components/ui';

type Call = { el: Element; frames: Keyframe[]; options: KeyframeAnimationOptions; anim: FakeAnimation };

class FakeAnimation {
  cancelled = false;
  private listeners = new Map<string, (() => void)[]>();
  private resolve!: () => void;
  private reject!: (e: unknown) => void;
  finished = new Promise<void>((res, rej) => {
    this.resolve = res;
    this.reject = rej;
  });
  constructor() {
    this.finished.catch(() => {});
  }
  addEventListener(type: string, fn: () => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  private emit(type: string) {
    this.listeners.get(type)?.forEach((fn) => fn());
  }
  finish() {
    this.resolve();
    this.emit('finish');
  }
  cancel() {
    this.cancelled = true;
    this.reject(new DOMException('cancelado', 'AbortError'));
    this.emit('cancel');
  }
}

let calls: Call[] = [];
let reduced = false;

beforeEach(() => {
  calls = [];
  reduced = false;
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true });
  Object.defineProperty(HTMLElement.prototype, 'animate', {
    configurable: true,
    writable: true,
    value(this: Element, frames: Keyframe[], options: KeyframeAnimationOptions) {
      const anim = new FakeAnimation();
      calls.push({ el: this, frames, options, anim });
      return anim;
    },
  });
  window.matchMedia = ((query: string) => ({
    matches: query.includes('prefers-reduced-motion') ? reduced : false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
  delete document.documentElement.dataset.motionPreference;
  localStorage.removeItem(MOTION_PREFERENCE_STORAGE_KEY);
  endSettling();
});

afterEach(() => {
  cleanup();
  cancelAllMotion();
  delete (HTMLElement.prototype as { animate?: unknown }).animate;
});

function mount(ui: ReactNode, api = new MockApi(), route: Route = { view: 'agenda' }, go = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AppContext.Provider value={{ api, route, go, toast: null, showToast: vi.fn(), dismissToast: vi.fn(), mockReason: 'fixture de prueba', reviewer: '', setReviewer: vi.fn(), openAssistant: vi.fn(), authMode: 'local' }}>
        {ui}
      </AppContext.Provider>
    </QueryClientProvider>,
  );
}

function must<T>(v: T | undefined): T {
  if (v === undefined) throw new Error('se esperaba un valor');
  return v;
}
const forTestId = (id: string) => calls.filter((c) => c.el.getAttribute('data-testid') === id);

describe('tiempos de la coreografía', () => {
  it('reparte las tarjetas en 40 ms y nunca excede los 480 ms de secuencia', () => {
    expect(staggerStep(1)).toBe(0);
    expect(staggerStep(5)).toBe(40);
    for (const n of [2, 5, 6, 10, 11, 50]) {
      const last = staggerStep(n) * (n - 1) + MOTION.card.duration;
      expect(last).toBeLessThanOrEqual(MOTION.card.maxTotal + 0.001);
    }
  });

  it('anima encabezado (260 ms, 14 px) y tarjetas (280 ms) con las duraciones acordadas', () => {
    const head = document.createElement('div');
    const cards = [document.createElement('div'), document.createElement('div'), document.createElement('div')];
    document.body.append(head, ...cards);
    playHeading(head);
    playCards(cards);
    expect(must(calls[0]).options.duration).toBe(260);
    expect(String(must(must(calls[0]).frames[0]).transform)).toContain('translateY(-14px)');
    expect(calls.slice(1).map((c) => [c.options.duration, c.options.delay])).toEqual([[280, 0], [280, 40], [280, 80]]);
    [head, ...cards].forEach((el) => el.remove());
  });

  it('con movimiento reducido no anima nada', () => {
    reduced = true;
    const el = document.createElement('div');
    document.body.append(el);
    expect(playHeading(el)).toBeNull();
    expect(playCards([el])).toEqual([]);
    expect(calls).toHaveLength(0);
    el.remove();
  });
});

describe('selector de movimiento reducido', () => {
  it('permite anular la preferencia del sistema y guarda los tres modos', async () => {
    reduced = true;
    document.documentElement.dataset.motionPreference = 'system';
    expect(reducedMotion()).toBe(true);

    await setMotionPreference('full');
    expect(reducedMotion()).toBe(false);
    expect(localStorage.getItem(MOTION_PREFERENCE_STORAGE_KEY)).toBe('full');

    await setMotionPreference('reduced');
    expect(reducedMotion()).toBe(true);
    expect(document.documentElement.dataset.motionPreference).toBe('reduced');

    reduced = false;
    await setMotionPreference('system');
    expect(reducedMotion()).toBe(false);
    expect(localStorage.getItem(MOTION_PREFERENCE_STORAGE_KEY)).toBe('system');
  });

  it('cancela los efectos decorativos en curso al activar movimiento reducido', async () => {
    const el = document.createElement('div');
    document.body.append(el);
    playHeading(el);
    const animation = must(calls[0]).anim;

    await setMotionPreference('reduced');

    expect(animation.cancelled).toBe(true);
    expect(playHeading(el)).toBeNull();
    el.remove();
  });

  it('expone un grupo segmentado con flechas y conserva el modo elegido', () => {
    render(<MotionPreferenceSwitch />);
    const group = screen.getByRole('radiogroup', { name: 'Movimiento reducido' });
    const system = screen.getByRole('radio', { name: 'Usar preferencia del sistema' });
    const reducedMode = screen.getByRole('radio', { name: 'Activar movimiento reducido' });
    expect(group).toBeTruthy();
    expect(system.getAttribute('aria-checked')).toBe('true');

    fireEvent.keyDown(system, { key: 'ArrowRight' });

    expect(reducedMode.getAttribute('aria-checked')).toBe('true');
    expect(document.activeElement).toBe(reducedMode);
    expect(document.documentElement.dataset.motionPreference).toBe('reduced');
    expect(localStorage.getItem(MOTION_PREFERENCE_STORAGE_KEY)).toBe('reduced');
  });
});

describe('agenda', () => {
  it('anima el encabezado al abrir y las tarjetas al llegar los datos; buscar no repite la animación', async () => {
    mount(<Agenda />);
    await screen.findAllByTestId('topic-card');
    const heading = calls.filter((c) => c.el.classList.contains('comic-page-heading'));
    const cards = calls.filter((c) => c.el.getAttribute('data-testid') === 'topic-card');
    expect(heading).toHaveLength(1);
    expect(cards.length).toBeGreaterThan(0);
    fireEvent.change(screen.getByTestId('agenda-search'), { target: { value: 'canal' } });
    await waitFor(() => expect(screen.getByTestId('agenda-count')).toBeTruthy());
    await new Promise((r) => setTimeout(r, 400));
    expect(calls.filter((c) => c.el.getAttribute('data-testid') === 'topic-card' || c.el.classList.contains('comic-page-heading'))).toHaveLength(
      heading.length + cards.length,
    );
  });

  it('«Ver más» anima solo las tarjetas nuevas', async () => {
    const api = new MockApi();
    const original = api.topics.bind(api);
    vi.spyOn(api, 'topics').mockImplementation(async (f) => {
      const base = await original({ ...f, limit: 1 });
      const proto = must(base.items[0]);
      const items = Array.from({ length: Math.min(f.limit ?? 5, 12) }, (_, i) => ({ ...proto, id: `t-${i}`, rank: i + 1 }));
      return { ...base, total: 12, items };
    });
    mount(<Agenda />, api);
    await screen.findAllByTestId('topic-card');
    const initial = calls.filter((c) => c.el.getAttribute('data-testid') === 'topic-card');
    expect(initial.map((c) => c.el.getAttribute('data-topic-id'))).toEqual(['t-0', 't-1', 't-2', 't-3', 't-4']);
    calls.length = 0;
    fireEvent.click(screen.getByTestId('agenda-more'));
    await waitFor(() => expect(screen.getAllByTestId('topic-card')).toHaveLength(12));
    const ids = calls.filter((c) => c.el.getAttribute('data-testid') === 'topic-card').map((c) => c.el.getAttribute('data-topic-id'));
    expect(ids).toEqual(['t-5', 't-6', 't-7', 't-8', 't-9', 't-10', 't-11']);
  });

  it('muestra los datos y los deja estables si la API falla; reintentar no deja efectos colgados', async () => {
    const api = new MockApi();
    const original = api.topics.bind(api);
    vi.spyOn(api, 'topics').mockRejectedValueOnce(new Error('sin red')).mockImplementation(original);
    mount(<Agenda />, api);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    await screen.findAllByTestId('topic-card');
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('botones y acciones', () => {
  it('la pulsación comprime a 0,97 con 2 px y 160 ms, y no añade ni retrasa clics', () => {
    const onClick = vi.fn();
    const off = installInteractions();
    render(<Button onClick={onClick}>Acción</Button>);
    const button = screen.getByRole('button', { name: 'Acción' });
    button.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0 }));
    expect(onClick).not.toHaveBeenCalled();
    const press = calls.find((c) => c.el === button);
    expect(press?.options.duration).toBe(160);
    expect(String(press?.frames[1]?.transform)).toBe('translateY(2px) scale(0.97)');
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
    off();
  });

  it('no anima controles deshabilitados ni ocupados', () => {
    const off = installInteractions();
    render(
      <>
        <Button disabled>Quieto</Button>
        <Button busy>Ocupado</Button>
      </>,
    );
    for (const name of ['Quieto', 'Ocupado']) {
      const b = screen.getByRole('button', { name });
      b.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0 }));
      fireEvent.click(b);
    }
    expect(calls).toHaveLength(0);
    off();
  });

  it('el teclado (Enter y Espacio) también comprime el botón', () => {
    const off = installInteractions();
    render(<Button>Teclado</Button>);
    const b = screen.getByRole('button', { name: 'Teclado' });
    fireEvent.keyDown(b, { key: 'Enter' });
    fireEvent.keyDown(b, { key: ' ' });
    fireEvent.keyDown(b, { key: 'a' });
    fireEvent.keyDown(b, { key: 'Enter', repeat: true });
    expect(calls.filter((c) => c.el === b)).toHaveLength(2);
    off();
  });

  it('las acciones principales con icono lanzan trazos de 180 ms decorativos y sin eventos de puntero', () => {
    const off = installInteractions();
    render(
      <>
        <Button variant="primary" icon={Bot}>Principal</Button>
        <Button icon={Bot}>Secundaria</Button>
      </>,
    );
    const primary = screen.getByRole('button', { name: 'Principal' });
    const ink = primary.querySelector('[data-ink]') as HTMLElement;
    expect(ink.getAttribute('aria-hidden')).toBe('true');
    expect(screen.getByRole('button', { name: 'Secundaria' }).querySelector('[data-ink]')).toBeNull();
    // Los trazos están fuera de la etiqueta: viven dentro del contenedor del icono, no del texto.
    expect(ink.closest('.comic-icon-slot')).not.toBeNull();
    fireEvent.click(primary);
    const burst = calls.find((c) => c.el === ink);
    expect(burst?.options.duration).toBe(180);
    off();
  });
});

describe('avisos y confirmaciones', () => {
  it('un error entra corto y sobrio; una confirmación entra en 220 ms con sello sobre el icono', async () => {
    render(
      <>
        <Notice tone="bad" role="alert" testId="n-bad">Falló</Notice>
        <Notice tone="ok" testId="n-ok" stamp title="Guardado" />
        <Notice tone="info" testId="n-quiet" animate={false} />
      </>,
    );
    await act(async () => {});
    const bad = must(forTestId('n-bad')[0]);
    const ok = must(forTestId('n-ok')[0]);
    expect(bad.options.duration).toBe(160);
    expect(bad.frames).toHaveLength(2);
    expect(ok.options.duration).toBe(220);
    const stamp = calls.find((c) => c.el.getAttribute('data-stamp') !== null);
    expect(stamp?.el.closest('[data-testid="n-ok"]')).not.toBeNull();
    expect(forTestId('n-quiet')).toHaveLength(0);
  });

  it('un aviso que aparece con su sección no se anima por su cuenta', async () => {
    settle(500);
    render(<Notice tone="warn" testId="n-with-section">Aviso</Notice>);
    await act(async () => {});
    expect(forTestId('n-with-section')).toHaveLength(0);
  });
});

