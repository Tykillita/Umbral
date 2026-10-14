import { afterEach, expect, it } from 'vitest';
import { activeScrollLocks, lockScroll } from './scrollLock';

afterEach(() => {
  document.body.style.overflow = '';
  document.documentElement.style.overflow = '';
});

it('bloquea el scroll y restaura el estado original al soltar el último bloqueo', () => {
  document.body.style.overflow = 'auto';
  const first = lockScroll();
  expect(document.body.style.overflow).toBe('hidden');
  expect(document.documentElement.style.overflow).toBe('hidden');
  first();
  expect(document.body.style.overflow).toBe('auto');
  expect(activeScrollLocks()).toBe(0);
});

it('no deja el scroll bloqueado aunque las superficies se cierren en distinto orden', () => {
  const a = lockScroll();
  const b = lockScroll();
  a(); // la primera en abrirse se cierra primero
  expect(document.body.style.overflow).toBe('hidden');
  b();
  expect(document.body.style.overflow).toBe('');
  expect(document.documentElement.style.overflow).toBe('');
});

it('soltar dos veces el mismo bloqueo no afecta a los demás', () => {
  const a = lockScroll();
  const b = lockScroll();
  a();
  a();
  expect(activeScrollLocks()).toBe(1);
  b();
  expect(activeScrollLocks()).toBe(0);
});
