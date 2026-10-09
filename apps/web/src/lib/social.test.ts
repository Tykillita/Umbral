import { describe, expect, it } from 'vitest';
import { socialVariants } from './social';

describe('variantes de copy social', () => {
  it('deriva texto del copy actual y respeta los límites por plataforma', () => {
    const variants = socialVariants('Un copy editorial revisado.');
    expect(variants.map((item) => item.platform)).toEqual(['X', 'Instagram', 'TikTok']);
    expect(variants.every((item) => item.text === 'Un copy editorial revisado.')).toBe(true);
    expect(variants.every((item) => item.characters <= item.limit)).toBe(true);
    expect(socialVariants('Copy editado')[0]?.text).toBe('Copy editado');
  });

  it('recorta en un límite de caracteres visibles y señala la variante truncada', () => {
    const variants = socialVariants('á'.repeat(2500));
    expect(variants.map((item) => item.characters)).toEqual([280, 2200, 150]);
    expect(variants.every((item) => item.truncated)).toBe(true);
    expect(variants.every((item) => item.text.endsWith('…'))).toBe(true);
  });

  it('retira marcadores técnicos de cita sin cambiar el contenido restante', () => {
    expect(socialVariants('Un dato confirmado [c3].')[0]?.text).toBe('Un dato confirmado.');
  });
});
