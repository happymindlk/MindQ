import { describe, expect, it } from 'vitest';
import { visibleSubscales } from './report-subscales';

describe('visibleSubscales', () => {
  it('hides a single subscale whose name matches the module exactly', () => {
    const facets = [{ name: 'Drive' }];
    expect(visibleSubscales('Drive', facets)).toEqual([]);
  });

  it('hides Personal Initiative Scale when the lone facet is Personal Initiative', () => {
    const facets = [{ name: 'Personal Initiative', positionPct: 72 }];
    expect(visibleSubscales('Personal Initiative Scale', facets)).toEqual([]);
  });

  it('hides CogniCheck single facets via the known-module list', () => {
    const facets = [{ name: 'Overall Cognitive Score', positionPct: 61 }];
    expect(visibleSubscales('CogniCheck', facets)).toEqual([]);
  });

  it('keeps a single unrelated facet', () => {
    const facets = [{ name: 'Reflective', positionPct: 40 }];
    expect(visibleSubscales('Work Style Inventory', facets)).toEqual(facets);
  });

  it('keeps multi-facet modules unchanged', () => {
    const facets = [
      { name: 'Extraversion', positionPct: 50 },
      { name: 'Agreeableness', positionPct: 55 },
    ];
    expect(visibleSubscales('Mini-IPIP', facets)).toEqual(facets);
  });

  it('returns an empty list unchanged', () => {
    expect(visibleSubscales('Any Module', [])).toEqual([]);
  });
});
