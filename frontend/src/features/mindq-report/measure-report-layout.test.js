import { describe, expect, it } from 'vitest';
import { measureReportLayout } from './render-report-pdf';

/**
 * @param {HTMLElement} el
 * @param {number} top
 * @param {number} bottom
 */
function place(el, top, bottom) {
  el.getBoundingClientRect = () => ({ top, bottom, left: 0, right: 800, width: 800, height: bottom - top });
  return el;
}

function buildRoot() {
  const root = place(document.createElement('div'), 100, 1700);
  const first = place(document.createElement('div'), 100, 600);
  first.setAttribute('data-pdf-block', '');
  const group = place(document.createElement('article'), 620, 1400);
  group.setAttribute('data-pdf-block', '');
  const rowA = place(document.createElement('li'), 660, 900);
  rowA.setAttribute('data-pdf-row', '');
  const rowB = place(document.createElement('li'), 900, 1380);
  rowB.setAttribute('data-pdf-row', '');
  group.append(rowA, rowB);
  const footer = place(document.createElement('footer'), 1500, 1620);
  footer.setAttribute('data-pdf-footer', '');
  root.append(first, group, footer);
  return root;
}

describe('measureReportLayout', () => {
  it('measures relative to the root and stops content at the footer', () => {
    const layout = measureReportLayout(buildRoot());
    expect(layout.contentHeight).toBe(1400);
    expect(layout.footer).toEqual({ top: 1400, bottom: 1520 });
    expect(layout.keepTogether).toEqual([
      { top: 0, bottom: 500 },
      { top: 520, bottom: 1300 },
    ]);
  });

  it('collects block and row edges as breakpoints but none from the footer', () => {
    const { breakpoints } = measureReportLayout(buildRoot());
    expect(breakpoints).toEqual(expect.arrayContaining([500, 520, 560, 800, 1280, 1300]));
    expect(breakpoints.every((b) => b < 1400)).toBe(true);
  });

  it('treats the whole report as content when there is no footer', () => {
    const root = buildRoot();
    root.querySelector('[data-pdf-footer]').remove();
    Object.defineProperty(root, 'scrollHeight', { value: 1600 });
    expect(measureReportLayout(root).contentHeight).toBe(1600);
    expect(measureReportLayout(root).footer).toBeNull();
  });
});
