import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RichText, parseBlocks } from './RichText';

const AGENDA = [
  '**Temas que merecen revisión** según `scoring-v1` (snapshot 20261007-cfa338b6).',
  '',
  'Basado únicamente en titular/metadatos: el puntaje ordena, no demuestra verdad.',
  '',
  '1. **Panama Canal Increases Daily Transits**',
  'Puntaje **76.70** (alto) · evidencia parcial.',
  '2. **Comisión de Presupuesto tramita traslados**',
  'Puntaje **74.55** (alto) · evidencia insuficiente.',
].join('\n');

describe('RichText', () => {
  it('separa párrafos y agrupa los ítems numerados con su segunda línea', () => {
    const blocks = parseBlocks(AGENDA);
    expect(blocks.map((b) => b.kind)).toEqual(['p', 'p', 'ol']);
    const list = blocks[2];
    expect(list && list.kind === 'ol' && list.items).toHaveLength(2);
    expect(list && list.kind === 'ol' && list.items[0]).toContain('\nPuntaje');
  });

  it('renderiza negritas, código, párrafos y lista sin HTML en crudo', () => {
    const { container } = render(<RichText text={AGENDA} testId="t" />);
    expect(container.querySelectorAll('p')).toHaveLength(2);
    expect(container.querySelectorAll('ol > li')).toHaveLength(2);
    expect(container.querySelectorAll('strong').length).toBeGreaterThanOrEqual(5);
    expect(container.querySelector('code')?.textContent).toBe('scoring-v1');
    expect(screen.getByTestId('t').textContent).not.toContain('**');
  });

  it('trata el marcado de una fuente como texto, no como HTML', () => {
    const { container } = render(<RichText text={'- <img src=x onerror=alert(1)> **ok**'} />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('ul > li')?.textContent).toContain('<img');
  });

  it('listas con viñetas y saltos de línea simples', () => {
    const { container } = render(<RichText text={'Verificaciones pendientes:\n- Confirmar fuente primaria\n- Contrastar cifra'} />);
    expect(container.querySelectorAll('ul > li')).toHaveLength(2);
    expect(container.querySelectorAll('p')).toHaveLength(1);
  });
});
