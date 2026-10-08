import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.{ts,tsx}'],
    // El recorrido con API exige un fixture/servidor explícito; nunca se da por aprobado si falta.
    exclude: process.env.UMBRAL_LIVE_TESTS === '1' ? [] : ['src/**/*.live.test.tsx'],
    setupFiles: [],
  },
});
