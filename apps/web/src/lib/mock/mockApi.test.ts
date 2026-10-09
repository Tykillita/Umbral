import { describe, expect, it } from 'vitest';
import { MockApi } from './mockApi';
import { MOCK_SPECS } from './data';

describe('filtro de oportunidad TVN en el mock', () => {
  it('exige dos procedencias independientes y ausencia de artículos TVN, combinable con categoría', async () => {
    const api = new MockApi();
    const result = await api.topics({ tvnGap: true, scope: 'all', limit: 100 });
    const expected = new Set(
      MOCK_SPECS.filter((spec) => new Set(spec.articles.map((article) => article.originKey)).size >= 2
        && !spec.articles.some((article) => article.isTvn)).map((spec) => spec.id),
    );
    expect(new Set(result.items.map((topic) => topic.id))).toEqual(expected);
    expect(result.applied.tvnGap).toBe(true);
    if (result.items[0]) {
      const category = result.items[0].category;
      const combined = await api.topics({ tvnGap: true, scope: 'all', category, limit: 100 });
      expect(combined.items.every((topic) => expected.has(topic.id) && topic.category === category)).toBe(true);
    }
  });
});
