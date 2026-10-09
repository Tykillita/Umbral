import { webcrypto } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { afterEach, expect, it, vi } from 'vitest';
import { parseSheets } from './labelSheets';

afterEach(() => vi.unstubAllGlobals());
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object')
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`)
      .join(',')}}`;
  return JSON.stringify(value);
}
async function sheets() {
  const body = {
    version: 1,
    snapshotId: '20261008-test',
    topics: [
      {
        id: 'a1',
        text: 'Titular real citado',
        outlet: 'Fuente',
        url: 'https://example.com',
        publishedAt: null,
        detectedAt: '2026-10-08T20:00:00Z',
        prediction: 'economia',
      },
    ],
    pairs: [],
    claims: [],
  };
  const bytes = await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(body)));
  return { ...body, sheetHash: Buffer.from(bytes).toString('hex') };
}
it('comprueba la huella y elimina predicciones del material visible', async () => {
  vi.stubGlobal('crypto', webcrypto);
  const parsed = await parseSheets(await sheets());
  expect(parsed.topics[0]).not.toHaveProperty('prediction');
});
it('rechaza hojas alteradas y referencias duplicadas', async () => {
  vi.stubGlobal('crypto', webcrypto);
  const value = await sheets();
  value.topics[0]!.text = 'Texto alterado';
  await expect(parseSheets(value)).rejects.toThrow(/huella/);
  value.topics.push(value.topics[0]!);
  await expect(parseSheets(value)).rejects.toThrow(/contrato/);
});
it('la huella y el contrato de las hojas generadas en Python son compatibles con el navegador', async () => {
  vi.stubGlobal('crypto', webcrypto);
  const generated = JSON.parse(
    await readFile(resolve(process.cwd(), 'public/etiquetado/hojas.json'), 'utf8'),
  );
  const parsed = await parseSheets(generated);
  expect(parsed.snapshotId).toBe(generated.snapshotId);
  expect(parsed.sheetHash).toBe(generated.sheetHash);
  expect(parsed.topics).toHaveLength(generated.topics.length);
  expect(parsed.pairs).toHaveLength(generated.pairs.length);
  expect(parsed.claims).toHaveLength(generated.claims.length);
  expect(parsed.topics.length).toBeGreaterThan(0);
  expect(parsed.claims.every((claim) => claim.citations.length > 0)).toBe(true);
});
