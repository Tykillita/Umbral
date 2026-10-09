import { act, cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Tooltip } from './controls';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

async function showByHover() {
  vi.useFakeTimers();
  const { container } = render(
    <Tooltip content="Minimizar">
      <button type="button" aria-label="Minimizar ventana">−</button>
    </Tooltip>,
  );
  const host = container.querySelector('[aria-describedby]');
  if (!host) throw new Error('Falta el contenedor del tooltip.');
  fireEvent.pointerEnter(host, { pointerType: 'mouse' });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(250);
  });
  expect(document.querySelector('.tooltip')).not.toBeNull();
  return { host };
}

it('oculta el tooltip si se pierde el evento pointerleave y el puntero continúa fuera', async () => {
  await showByHover();

  fireEvent.pointerMove(document.body, { pointerType: 'mouse' });

  expect(document.querySelector('.tooltip')).toBeNull();
});

it('oculta el tooltip cuando la ventana de escritorio pierde el foco', async () => {
  await showByHover();

  fireEvent(window, new Event('blur'));

  expect(document.querySelector('.tooltip')).toBeNull();
});

it('oculta el tooltip al salir del botón y cancela su temporizador', async () => {
  const { host } = await showByHover();

  fireEvent.pointerLeave(host, { pointerType: 'mouse' });

  expect(document.querySelector('.tooltip')).toBeNull();
});
