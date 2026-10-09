/**
 * Split a tall report into page slices, preferring to cut at block boundaries
 * so sections, tables rows, and question cards are not sliced through.
 *
 * A page only breaks early at a boundary once it is at least `minFill` full;
 * otherwise a single oversized block would produce a near-empty page. When no
 * acceptable boundary exists the slice is hard-cut at the page height.
 *
 * @param {number} totalHeight Rendered report height (CSS px).
 * @param {number} pageHeight Printable height per page (CSS px).
 * @param {number[]} breakpoints Y offsets (CSS px) where a cut is safe.
 * @param {number} [minFill=0.6] Minimum page fill ratio before an early break.
 * @returns {{ start: number, end: number }[]}
 */
export function computePageSlices(totalHeight, pageHeight, breakpoints, minFill = 0.6) {
  if (!(totalHeight > 0) || !(pageHeight > 0)) return [];
  const sorted = [
    ...new Set(
      breakpoints
        .filter((b) => Number.isFinite(b) && b > 0 && b < totalHeight)
        .map((b) => Math.round(b)),
    ),
  ].sort((a, b) => a - b);

  const slices = [];
  let start = 0;
  while (totalHeight - start > pageHeight) {
    const limit = start + pageHeight;
    const floor = start + pageHeight * minFill;
    let end = limit;
    for (const b of sorted) {
      if (b > limit) break;
      if (b >= floor) end = b;
    }
    slices.push({ start, end });
    start = end;
  }
  slices.push({ start, end: totalHeight });
  return slices;
}
