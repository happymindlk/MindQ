import { describe, expect, it } from 'vitest';
import { footerHtmlForPdf, measureReportLayout, reportHtmlForPdf } from './render-report-pdf';

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
      { top: 560, bottom: 800 },
      { top: 800, bottom: 1280 },
    ]);
  });

  it('treats each module card row as an atomic keep-together range', () => {
    const { keepTogether } = measureReportLayout(buildRoot());
    expect(keepTogether).toEqual(
      expect.arrayContaining([
        { top: 560, bottom: 800 },
        { top: 800, bottom: 1280 },
      ]),
    );
  });

  it('collects block and row edges as breakpoints but none from the footer', () => {
    const { breakpoints } = measureReportLayout(buildRoot());
    expect(breakpoints).toEqual(expect.arrayContaining([500, 520, 560, 800, 1280, 1300]));
    expect(breakpoints.every((b) => b < 1400)).toBe(true);
  });

  it('rasterizes the body without the footer or same-origin font links', () => {
    const root = buildRoot();
    root.className = 'mindq-report';
    const fonts = document.createElement('style');
    fonts.setAttribute('data-report-fonts', '');
    fonts.textContent = '@font-face{src:url("/assets/x.woff2")}';
    const spacer = document.createElement('div');
    spacer.setAttribute('data-pdf-print-only', '');
    root.prepend(fonts, spacer);

    const html = reportHtmlForPdf(root, '@font-face{src:url("data:font/woff2;base64,AA")}');
    expect(html.startsWith('<style>@font-face{src:url("data:font/woff2;base64,AA")}</style>')).toBe(true);
    expect(html).not.toContain('data-pdf-footer');
    expect(html).not.toContain('/assets/x.woff2');
    expect(html).not.toContain('data-pdf-print-only');
    // The live DOM is untouched.
    expect(root.querySelector('[data-pdf-footer]')).toBeTruthy();
  });

  it('rasterizes the footer alone inside a padded report wrapper', () => {
    const html = footerHtmlForPdf(buildRoot(), null);
    expect(html).toContain('class="mindq-report"');
    expect(html).toContain('data-pdf-footer');
    expect(html).toContain('margin-top: 0');
    expect(html).not.toContain('data-pdf-block=""');
  });

  it('returns no footer markup when the report has none', () => {
    const root = buildRoot();
    root.querySelector('[data-pdf-footer]').remove();
    expect(footerHtmlForPdf(root, null)).toBeNull();
  });

  it('treats the whole report as content when there is no footer', () => {
    const root = buildRoot();
    root.querySelector('[data-pdf-footer]').remove();
    Object.defineProperty(root, 'scrollHeight', { value: 1600 });
    expect(measureReportLayout(root).contentHeight).toBe(1600);
    expect(measureReportLayout(root).footer).toBeNull();
  });
});
