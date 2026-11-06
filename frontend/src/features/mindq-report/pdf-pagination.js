/**
 * @typedef {{ top: number, bottom: number }} KeepRange
 * @typedef {(end: number, start: number) => number} CutAdjuster
 * @typedef {{ minFill?: number, keepTogether?: KeepRange[], adjustCut?: CutAdjuster }} SliceOptions
 */

/**
 * Scan upward from `from` for a cut line with no ink on it or just above it.
 *
 * Guards the raster PDF against slicing glyphs horizontally when a planned
 * cut lands on a text line (e.g. layout measured with different metrics than
 * the rasterized image).
 *
 * @param {(y: number) => boolean} hasInk Whether CSS-px row `y` contains ink.
 * @param {number} from Planned cut (CSS px).
 * @param {number} to Lowest acceptable cut (CSS px), `to < from`.
 * @param {number} [clearRows] Consecutive ink-free rows required above the cut.
 * @returns {number | null} Adjusted cut, or null when no clean row exists.
 */
export function findInkFreeCut(hasInk, from, to, clearRows = 2) {
  const top = Math.ceil(to);
  for (let y = Math.floor(from); y - clearRows >= top; y -= 1) {
    let clear = !hasInk(y);
    for (let k = 1; clear && k <= clearRows; k += 1) clear = !hasInk(y - k);
    if (clear) return y;
  }
  return null;
}

/**
 * @param {number[]} breakpoints
 * @param {number} totalHeight
 * @returns {number[]}
 */
function normalizeBreakpoints(breakpoints, totalHeight) {
  return [
    ...new Set(
      breakpoints
        .filter((b) => Number.isFinite(b) && b > 0 && b < totalHeight)
        .map((b) => Math.round(b)),
    ),
  ].sort((a, b) => a - b);
}

/**
 * Split a tall report into A4 page slices without clipping cards mid-text.
 *
 * Mirrors CSS `break-inside: avoid` for the raster PDF: a cut never lands
 * inside a keep-together range that fits on one page, so such a block moves
 * whole to the next page. Ranges taller than a page may still be split, but
 * only at a breakpoint (e.g. between score rows).
 *
 * Preference order per page:
 *   1. last safe breakpoint with the page at least `minFill` full;
 *   2. otherwise the last breakpoint past `minFill` (or a hard cut at the page
 *      height), unless that would clip a keep-together block, in which case
 *   3. the last safe breakpoint anywhere on the page (block moves down whole).
 * The chosen cut is then passed to `adjustCut`, which may only move it up.
 *
 * @param {number} totalHeight Rendered content height (CSS px).
 * @param {number} pageHeight Printable height per page (CSS px).
 * @param {number[]} breakpoints Y offsets (CSS px) where a cut is acceptable.
 * @param {SliceOptions} [options]
 * @returns {{ start: number, end: number }[]}
 */
export function computePageSlices(totalHeight, pageHeight, breakpoints, options = {}) {
  if (!(totalHeight > 0) || !(pageHeight > 0)) return [];
  const { minFill = 0.6, keepTogether = [], adjustCut } = options;
  const sorted = normalizeBreakpoints(breakpoints, totalHeight);
  const keeps = keepTogether.filter(
    (k) =>
      Number.isFinite(k.top) &&
      Number.isFinite(k.bottom) &&
      k.bottom > k.top &&
      k.bottom - k.top <= pageHeight,
  );

  const slices = [];
  let start = 0;
  while (totalHeight - start > pageHeight) {
    const limit = start + pageHeight;
    const floor = start + pageHeight * minFill;
    const isSafe = (b) => !keeps.some((k) => k.top >= start && k.top < b && b < k.bottom);

    let preferred = null;
    let anySafe = null;
    let filled = null;
    for (const b of sorted) {
      if (b <= start) continue;
      if (b > limit) break;
      const safe = isSafe(b);
      if (safe) anySafe = b;
      if (b >= floor) {
        filled = b;
        if (safe) preferred = b;
      }
    }
    const fallback = filled ?? limit;
    let end = preferred ?? (isSafe(fallback) ? fallback : (anySafe ?? fallback));
    if (adjustCut) {
      const adjusted = Math.round(adjustCut(end, start));
      // Only ever move a cut up, and never to (or above) the page start.
      if (Number.isFinite(adjusted) && adjusted > start && adjusted <= end) end = adjusted;
    }
    slices.push({ start, end });
    start = end;
  }
  slices.push({ start, end: totalHeight });
  return slices;
}
