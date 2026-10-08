import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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

  it('convierte [n] en botones solo cuando hay fuente n y no dentro de una cita entre «»', () => {
    const onCite = vi.fn();
    const { container } = render(<RichText text={'Hay un titular [1] y otro dato [2]. Cita: «Noticia [2] literal» y [9].'} citing={{ count: 2, onCite }} />);
    const markers = container.querySelectorAll('button.cite-marker');
    expect([...markers].map((item) => item.getAttribute('data-cite-index'))).toEqual(['1', '2']);
    expect(container.textContent).toContain('«Noticia [2] literal»');
    expect(container.textContent).toContain('[9]');
    fireEvent.click(markers[1]!);
    expect(onCite).toHaveBeenCalledWith(2);
  });

  it('no crea botones sin contexto de citas', () => {
    const { container } = render(<RichText text="Texto con [1] suelto" />);
    expect(container.querySelectorAll('button')).toHaveLength(0);
    expect(container.textContent).toBe('Texto con [1] suelto');
  });
});

