export type SocialPlatform = 'X' | 'Instagram' | 'TikTok';

export const SOCIAL_LIMITS: Record<SocialPlatform, number> = {
  X: 280,
  Instagram: 2200,
  TikTok: 150,
};

export interface SocialVariant {
  platform: SocialPlatform;
  limit: number;
  text: string;
  characters: number;
  truncated: boolean;
}

function fit(text: string, limit: number): { text: string; truncated: boolean } {
  const clean = text.trim().replace(/\s*\[c\d+\]/g, '');
  const chars = [...clean];
  if (chars.length <= limit) return { text: clean, truncated: false };

  const prefix = chars.slice(0, limit - 1).join('');
  const boundary = prefix.lastIndexOf(' ');
  const excerpt = (boundary > 0 ? prefix.slice(0, boundary) : prefix).trimEnd();
  return { text: `${excerpt}…`, truncated: true };
}

/** Variantes derivadas en tiempo real del copy validado/editado, sin añadir datos. */
export function socialVariants(copy: string): SocialVariant[] {
  return (Object.entries(SOCIAL_LIMITS) as [SocialPlatform, number][]).map(([platform, limit]) => {
    const fitted = fit(copy, limit);
    return {
      platform,
      limit,
      text: fitted.text,
      characters: [...fitted.text].length,
      truncated: fitted.truncated,
    };
  });
}
