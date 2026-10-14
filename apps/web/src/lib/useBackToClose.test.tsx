import { act, cleanup, render } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { overlayDepth, useBackToClose } from './useBackToClose';

function Overlay({ open, onClose }: { open: boolean; onClose: () => void }) {
  useBackToClose(open, onClose);
  return null;
}

afterEach(() => cleanup());

const pop = () => act(() => { window.dispatchEvent(new PopStateEvent('popstate', { state: null })); });

it('al abrir añade una entrada de historial y Atrás cierra la superficie', () => {
  const before = window.history.length;
  const onClose = vi.fn();
  render(<Overlay open onClose={onClose} />);
  expect(window.history.length).toBe(before + 1);
  expect(overlayDepth()).toBe(1);
  pop();
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(overlayDepth()).toBe(0);
});

it('con dos superficies apiladas, Atrás cierra solo la de arriba', () => {
  const lower = vi.fn();
  const upper = vi.fn();
  render(<><Overlay open onClose={lower} /><Overlay open onClose={upper} /></>);
  expect(overlayDepth()).toBe(2);
  pop();
  expect(upper).toHaveBeenCalledTimes(1);
  expect(lower).not.toHaveBeenCalled();
});

it('si se cierra por otro medio no llama a onClose ni deja una entrada colgada', () => {
  const onClose = vi.fn();
  const { rerender } = render(<Overlay open onClose={onClose} />);
  rerender(<Overlay open={false} onClose={onClose} />);
  expect(overlayDepth()).toBe(0);
  expect(onClose).not.toHaveBeenCalled();
});

it('cerrada no toca el historial', () => {
  const before = window.history.length;
  render(<Overlay open={false} onClose={() => undefined} />);
  expect(window.history.length).toBe(before);
});
