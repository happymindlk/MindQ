import { describe, expect, it } from 'vitest';
import { computePageSlices, findInkFreeCut } from './pdf-pagination';

/**
 * @param {[number, number][]} lines Inked [top, bottom) CSS-px ranges.
 * @returns {(y: number) => boolean}
 */
const inkAt = (lines) => (y) => lines.some(([top, bottom]) => y >= top && y < bottom);

describe('findInkFreeCut', () => {
  it('keeps a cut that already sits on clean rows', () => {
    expect(findInkFreeCut(inkAt([[100, 116]]), 130, 80)).toBe(130);
  });

  it('moves a cut off a text line to the clean gap above it', () => {
    // Line 980-996 straddles the planned cut at 990; the gap above ends at 979.
    const hasInk = inkAt([[950, 966], [980, 996]]);
    const cut = findInkFreeCut(hasInk, 990, 900);
    expect(cut).toBe(979);
    expect(hasInk(cut)).toBe(false);
  });

  it('returns null when every row in range carries ink', () => {
    expect(findInkFreeCut(inkAt([[0, 2000]]), 990, 900)).toBeNull();
  });
});

describe('computePageSlices with adjustCut', () => {
  it('applies the adjuster and continues the next page from the adjusted cut', () => {
    const slices = computePageSlices(2500, 1000, [950, 1900], { adjustCut: (end) => end - 10 });
    expect(slices[0]).toEqual({ start: 0, end: 940 });
    expect(slices[1].start).toBe(940);
    expect(slices.at(-1).end).toBe(2500);
  });

  it('ignores adjustments that move a cut down or to the page start', () => {
    expect(computePageSlices(2000, 1000, [950], { adjustCut: (end) => end + 50 })[0].end).toBe(950);
    expect(computePageSlices(2000, 1000, [950], { adjustCut: () => 0 })[0].end).toBe(950);
  });

  it('never slices a glyph when the planned hard cut lands on a text line', () => {
    // No breakpoints at all: the planned cut is a hard cut at 1000, mid-line.
    const lines = Array.from({ length: 120 }, (_, i) => [i * 20 + 4, i * 20 + 18]);
    const hasInk = inkAt(lines);
    const slices = computePageSlices(2400, 1000, [], {
      adjustCut: (end, start) => findInkFreeCut(hasInk, end, start + 1) ?? end,
    });
    slices.slice(0, -1).forEach((s) => {
      expect(hasInk(s.end)).toBe(false);
      expect(hasInk(s.end - 1)).toBe(false);
    });
  });
});

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

  it('moves a keep-together card to the next page instead of clipping it', () => {
    // Card spans 700-1200; a 1000px page would otherwise cut it at 1000.
    const slices = computePageSlices(2000, 1000, [300, 700, 1000, 1200], {
      keepTogether: [{ top: 700, bottom: 1200 }],
    });
    expect(slices[0]).toEqual({ start: 0, end: 700 });
    expect(slices[1].start).toBe(700);
  });

  it('pushes a card down even when the page ends up less than minFill full', () => {
    const slices = computePageSlices(1800, 1000, [250, 1100], {
      keepTogether: [{ top: 250, bottom: 1100 }],
    });
    expect(slices[0]).toEqual({ start: 0, end: 250 });
  });

  it('splits an oversized group only between rows', () => {
    // Group 100-2300 is taller than a page; rows end every 200px inside it.
    const rows = [300, 500, 700, 900, 1100, 1300, 1500, 1700, 1900, 2100];
    const slices = computePageSlices(2400, 1000, [100, ...rows, 2300], {
      keepTogether: [{ top: 100, bottom: 2300 }],
    });
    expect(slices[0].end).toBe(900);
    slices.slice(0, -1).forEach((s) => expect([100, ...rows, 2300]).toContain(s.end));
  });

  it('keeps short cards whole while a long section flows across pages (3 vs 6 tests)', () => {
    const build = (count) => {
      const keeps = [{ top: 0, bottom: 900 }];
      const points = [900];
      let y = 900;
      for (let i = 0; i < count; i += 1) {
        keeps.push({ top: y, bottom: y + 320 });
        y += 320;
        points.push(y);
      }
      return { total: y, keeps, points };
    };
    [3, 6].forEach((count) => {
      const { total, keeps, points } = build(count);
      const slices = computePageSlices(total, 1000, points, { keepTogether: keeps });
      slices.slice(0, -1).forEach((s) => {
        keeps.forEach((k) => expect(k.top < s.end && s.end < k.bottom).toBe(false));
      });
      expect(slices.at(-1).end).toBe(total);
    });
  });

  it('returns nothing for degenerate sizes', () => {
    expect(computePageSlices(0, 1000, [])).toEqual([]);
    expect(computePageSlices(1000, 0, [])).toEqual([]);
  });
});
