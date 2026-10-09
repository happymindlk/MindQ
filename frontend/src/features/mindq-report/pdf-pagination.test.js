import { describe, expect, it } from 'vitest';
import { computePageSlices } from './pdf-pagination';

describe('computePageSlices', () => {
  it('returns one slice when content fits a page', () => {
    expect(computePageSlices(500, 1000, [100, 200])).toEqual([{ start: 0, end: 500 }]);
  });

  it('breaks at the last block boundary that fits', () => {
    expect(computePageSlices(2500, 1000, [700, 950, 1600, 1900])).toEqual([
      { start: 0, end: 950 },
      { start: 950, end: 1900 },
      { start: 1900, end: 2500 },
    ]);
  });

  it('hard-cuts when the only boundary would leave a mostly empty page', () => {
    expect(computePageSlices(2000, 1000, [200])).toEqual([
      { start: 0, end: 1000 },
      { start: 1000, end: 2000 },
    ]);
  });

  it('ignores invalid and out-of-range breakpoints', () => {
    expect(computePageSlices(1500, 1000, [NaN, -5, 0, 1500, 9999, 800.4])).toEqual([
      { start: 0, end: 800 },
      { start: 800, end: 1500 },
    ]);
  });

  it('always makes forward progress and covers the full height', () => {
    const slices = computePageSlices(10000, 977, Array.from({ length: 200 }, (_, i) => i * 49));
    expect(slices[0].start).toBe(0);
    expect(slices.at(-1).end).toBe(10000);
    for (let i = 1; i < slices.length; i += 1) {
      expect(slices[i].start).toBe(slices[i - 1].end);
      expect(slices[i].end).toBeGreaterThan(slices[i].start);
    }
  });

  it('returns nothing for degenerate sizes', () => {
    expect(computePageSlices(0, 1000, [])).toEqual([]);
    expect(computePageSlices(1000, 0, [])).toEqual([]);
  });
});
