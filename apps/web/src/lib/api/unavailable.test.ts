import { describe, expect, it } from 'vitest';
import { ApiError, describeError, isServiceUnavailable } from './client';

describe('servicio no disponible', () => {
  it('reconoce sin conexión, 5xx y el 404 del proxy como servicio no disponible', () => {
    expect(isServiceUnavailable(new ApiError(0, null))).toBe(true);
    expect(isServiceUnavailable(new ApiError(502, null))).toBe(true);
    expect(isServiceUnavailable(new ApiError(503, { code: 'inicio_agotado', message: 'x' }))).toBe(true);
    expect(isServiceUnavailable(new ApiError(404, null))).toBe(true); // sin cuerpo de Umbral → código `error_http`
  });

  it('no confunde un rechazo de la API con un servicio caído', () => {
    expect(isServiceUnavailable(new ApiError(404, { code: 'tema_no_encontrado', message: 'No existe ese tema.' }))).toBe(false);
    expect(isServiceUnavailable(new ApiError(409, { code: 'conflicto', message: 'x' }))).toBe(false);
    expect(isServiceUnavailable(new ApiError(429, null))).toBe(false);
    expect(isServiceUnavailable(new ApiError(0, { code: 'almacenamiento_bloqueado', message: 'x' }))).toBe(false);
    expect(isServiceUnavailable(new Error('otro'))).toBe(false);
  });

  it('nunca muestra «Error HTTP …» crudo cuando el servicio no está disponible', () => {
    for (const status of [404, 500, 502, 503, 504]) {
      const text = describeError(new ApiError(status, null));
      expect(text).not.toMatch(/Error HTTP/);
      expect(text).toMatch(/no está disponible/);
      expect(text).toMatch(/trabajo guardado/);
    }
  });

  it('conserva el mensaje propio de la API en un 404 con cuerpo de Umbral', () => {
    expect(describeError(new ApiError(404, { code: 'tema_no_encontrado', message: 'No existe ese tema.' }))).toBe('No existe ese tema.');
  });
});
