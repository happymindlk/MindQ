import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { jsPDF } from 'jspdf';
import MindQReport from './mindq-report';
import { safeLogoUrl } from './report-logo';
import { computePageSlices, findInkFreeCut } from './pdf-pagination';
import { ensureReportFontsLoaded, inlinedReportFontCss } from './report-fonts';
import { reportFilename } from './report-filename';
import { REPORT_CSS, REPORT_WIDTH_PX } from './report-styles';

/** Match `@page` margins in report-styles.js: 15mm 15mm 20mm 15mm. */
const PAGE_MARGIN_X_MM = 15;
const PAGE_MARGIN_TOP_MM = 15;
const PAGE_MARGIN_BOTTOM_MM = 20;
const FOOTER_GAP_MM = 3;
const PAGE_NUMBER_BAND_MM = 4;
const MAX_CANVAS_HEIGHT_PX = 30000;
const MAX_LOGO_BYTES = 2 * 1024 * 1024;
const LOGO_FETCH_TIMEOUT_MS = 8000;
/** Report body padding (see `.mindq-report` in report-styles.js). */
const REPORT_PAD_X_PX = 32;
/** Rows darker than this luma count as text/bar ink; card borders stay lighter. */
const INK_LUMA = 170;
/** Any channel below this counts as non-background when trimming whitespace. */
const PAPER_CHANNEL = 248;
/** How far (fraction of a page) a cut may move up to find an ink-free row. */
const MAX_CUT_SHIFT = 0.25;

/**
 * Inline the corporate logo as a data URL. SVG foreignObject rasterization
 * refuses to load external images, so a remote URL would render blank in the PDF.
 *
 * @param {string | null | undefined} url
 * @returns {Promise<string | null>} Data URL, or null to fall back to the monogram.
 */
export async function inlineLogo(url) {
  const safe = safeLogoUrl(url);
  if (!safe) return null;
  if (safe.startsWith('data:')) return safe;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), LOGO_FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(safe, { mode: 'cors', credentials: 'omit', signal: controller.signal });
    if (!res.ok) return null;
    const blob = await res.blob();
    if (!blob.type.startsWith('image/') || blob.size > MAX_LOGO_BYTES) return null;
    return await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : null);
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    });
  } catch (err) {
    console.warn('mindq_report_logo_inline_failed', err);
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * @param {string} html
 * @returns {string}
 */
function toXmlCompatibleHtml(html) {
  return html
    .replace(/&nbsp;/g, '&#160;')
    .replace(/<br>/gi, '<br/>')
    .replace(/<hr>/gi, '<hr/>')
    .replace(/<img([^>]*?)(?<!\/)>/gi, '<img$1/>');
}

/**
 * @param {string | null} fontCss
 * @returns {string}
 */
function fontStyleTag(fontCss) {
  return fontCss ? `<style>${fontCss}</style>` : '';
}

/**
 * Clone the report body for SVG capture.
 *
 * Drops print-only spacer nodes (stray glyphs under foreignObject), the
 * same-origin font links (unreachable from the sandboxed SVG image), and the
 * footer, which is rasterized on its own and stamped onto every page.
 *
 * @param {HTMLElement} root
 * @param {string | null} fontCss Data-URL `@font-face` rules for the SVG image.
 * @returns {string}
 */
export function reportHtmlForPdf(root, fontCss) {
  const clone = /** @type {HTMLElement} */ (root.cloneNode(true));
  clone
    .querySelectorAll('[data-pdf-print-only], [data-report-fonts], [data-pdf-footer]')
    .forEach((el) => el.remove());
  return `${fontStyleTag(fontCss)}${clone.outerHTML}`;
}

/**
 * Standalone footer markup, wrapped so report-scoped styles still apply and
 * its width matches the footer inside the padded report body.
 *
 * @param {HTMLElement} root
 * @param {string | null} fontCss
 * @returns {string | null}
 */
export function footerHtmlForPdf(root, fontCss) {
  const footer = root.querySelector('[data-pdf-footer]');
  if (!(footer instanceof HTMLElement)) return null;
  const clone = /** @type {HTMLElement} */ (footer.cloneNode(true));
  clone.style.marginTop = '0';
  return (
    `${fontStyleTag(fontCss)}<div class="mindq-report" style="padding:0 ${REPORT_PAD_X_PX}px;">` +
    `<style>${REPORT_CSS}</style>${clone.outerHTML}</div>`
  );
}

/**
 * Rasterize report HTML via SVG foreignObject (never touches Tailwind stylesheets).
 *
 * @param {string} reportHtml
 * @param {number} widthPx
 * @param {number} heightPx
 * @param {number} scale
 * @returns {Promise<HTMLCanvasElement>}
 */
function rasterizeReportHtml(reportHtml, widthPx, heightPx, scale) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${widthPx}" height="${heightPx}">` +
    `<foreignObject width="100%" height="100%">` +
    `<div xmlns="http://www.w3.org/1999/xhtml" style="background:#ffffff;width:${widthPx}px;margin:0;">` +
    `${toXmlCompatibleHtml(reportHtml)}</div>` +
    `</foreignObject></svg>`;

  // data: URI avoids blob-URL canvas tainting with foreignObject in Chromium.
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(widthPx * scale);
      canvas.height = Math.ceil(heightPx * scale);
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('Canvas unavailable for PDF capture'));
        return;
      }
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      resolve(canvas);
    };
    img.onerror = () => reject(new Error('Failed to rasterize the MindQ Report for PDF'));
    img.src = url;
  });
}

/**
 * @typedef {{ top: number, bottom: number }} Range
 * @typedef {{
 *   contentHeight: number,
 *   breakpoints: number[],
 *   keepTogether: Range[],
 *   footer: Range | null,
 * }} ReportLayout
 */

/**
 * Measure pagination hints relative to the report root.
 *
 * Content stops where the footer starts: the footer is stamped onto every
 * page separately instead of appearing once at the end.
 *
 * @param {HTMLElement} root
 * @returns {ReportLayout}
 */
export function measureReportLayout(root) {
  const rootTop = root.getBoundingClientRect().top;
  const rangeOf = (el) => {
    const rect = el.getBoundingClientRect();
    return { top: rect.top - rootTop, bottom: rect.bottom - rootTop };
  };

  const footerEl = root.querySelector('[data-pdf-footer]');
  const footer = footerEl ? rangeOf(footerEl) : null;
  const contentHeight = footer ? footer.top : root.scrollHeight;

  const blocks = [...root.querySelectorAll('[data-pdf-block]')].map(rangeOf);
  // Module cards (rows) are atomic too: an oversized category group may only
  // split between cards, never through one.
  const rows = [...root.querySelectorAll('[data-pdf-row], tr')].map(rangeOf);
  const keepTogether = [...blocks, ...rows];
  const breakpoints = [];
  keepTogether.forEach((r) => breakpoints.push(r.top, r.bottom));

  return {
    contentHeight,
    breakpoints: breakpoints.filter((b) => b < contentHeight),
    keepTogether: keepTogether.filter((r) => r.bottom <= contentHeight),
    footer,
  };
}

/**
 * @param {HTMLCanvasElement} source
 * @param {number} scale
 * @param {number} topPx
 * @param {number} heightPx
 * @returns {HTMLCanvasElement}
 */
function cropCanvas(source, scale, topPx, heightPx) {
  const out = document.createElement('canvas');
  out.width = source.width;
  out.height = Math.max(1, Math.round(heightPx * scale));
  const ctx = out.getContext('2d');
  if (!ctx) throw new Error('Canvas unavailable for PDF pagination');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(
    source,
    0,
    Math.round(topPx * scale),
    source.width,
    out.height,
    0,
    0,
    out.width,
    out.height,
  );
  return out;
}

/**
 * Row-wise ink probe over a rasterized canvas, in CSS px.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {number} scale Canvas px per CSS px.
 * @returns {(y: number) => boolean}
 */
function createInkProbe(canvas, scale) {
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const cache = new Map();
  return (y) => {
    if (cache.has(y)) return cache.get(y);
    let ink = false;
    const top = Math.floor(y * scale);
    const rows = Math.max(1, Math.ceil(scale));
    if (ctx && top >= 0 && top + rows <= canvas.height) {
      const { data } = ctx.getImageData(0, top, canvas.width, rows);
      for (let i = 0; i < data.length; i += 4) {
        if (0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2] < INK_LUMA) {
          ink = true;
          break;
        }
      }
    }
    cache.set(y, ink);
    return ink;
  };
}

/**
 * Bottom of the last non-background row, in CSS px (rounded up).
 *
 * @param {HTMLCanvasElement} canvas
 * @param {number} scale
 * @returns {number}
 */
function paintedHeight(canvas, scale) {
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return canvas.height / scale;
  const chunk = 64;
  for (let bottom = canvas.height; bottom > 0; bottom -= chunk) {
    const top = Math.max(0, bottom - chunk);
    const { data } = ctx.getImageData(0, top, canvas.width, bottom - top);
    for (let row = bottom - top - 1; row >= 0; row -= 1) {
      const offset = row * canvas.width * 4;
      for (let i = offset; i < offset + canvas.width * 4; i += 4) {
        if (data[i] < PAPER_CHANNEL || data[i + 1] < PAPER_CHANNEL || data[i + 2] < PAPER_CHANNEL) {
          return Math.ceil((top + row + 1) / scale);
        }
      }
    }
  }
  return 0;
}

/**
 * Build a paginated A4 PDF from the rasterized report body, stamping the
 * separately rasterized footer at the bottom of every page.
 *
 * @param {HTMLCanvasElement} canvas Report body (footer excluded).
 * @param {HTMLCanvasElement | null} footerCanvas Footer only, already trimmed.
 * @param {number} scale Canvas px per CSS px.
 * @param {number} widthPx Report width (CSS px).
 * @param {ReportLayout} layout
 * @returns {Blob}
 */
function canvasToPdfBlob(canvas, footerCanvas, scale, widthPx, layout) {
  const pdf = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const usableWidth = pageWidth - PAGE_MARGIN_X_MM * 2;
  const mmPerPx = usableWidth / widthPx;

  const footerHeightPx = footerCanvas ? footerCanvas.height / scale : 0;
  const footerHeightMm = footerHeightPx * mmPerPx;
  // PNG keeps the MindQ wordmark legible; JPEG artifacts were reading as "Mincla".
  const footerImage = footerCanvas ? footerCanvas.toDataURL('image/png') : null;

  const usableHeight =
    pageHeight -
    PAGE_MARGIN_TOP_MM -
    PAGE_MARGIN_BOTTOM_MM -
    footerHeightMm -
    FOOTER_GAP_MM -
    PAGE_NUMBER_BAND_MM;
  const pageHeightPx = usableHeight / mmPerPx;

  // The image, not the DOM measurement, decides where content really ends.
  const contentHeight = Math.max(1, Math.min(canvas.height / scale, paintedHeight(canvas, scale) + 8));
  const hasInk = createInkProbe(canvas, scale);
  const slices = computePageSlices(contentHeight, pageHeightPx, layout.breakpoints, {
    keepTogether: layout.keepTogether,
    adjustCut: (end, start) =>
      findInkFreeCut(hasInk, end, Math.max(start + 1, end - pageHeightPx * MAX_CUT_SHIFT)) ?? end,
  });
  slices.forEach((slice, index) => {
    const sliceHeightPx = slice.end - slice.start;
    const pageCanvas = cropCanvas(canvas, scale, slice.start, sliceHeightPx);

    if (index > 0) pdf.addPage();
    pdf.addImage(
      pageCanvas.toDataURL('image/png'),
      'PNG',
      PAGE_MARGIN_X_MM,
      PAGE_MARGIN_TOP_MM,
      usableWidth,
      sliceHeightPx * mmPerPx,
    );

    const pageNumberY = pageHeight - PAGE_MARGIN_BOTTOM_MM;
    if (footerImage) {
      pdf.addImage(
        footerImage,
        'PNG',
        PAGE_MARGIN_X_MM,
        pageNumberY - PAGE_NUMBER_BAND_MM - footerHeightMm,
        usableWidth,
        footerHeightMm,
      );
    }
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(8);
    pdf.setTextColor(107, 114, 128);
    pdf.text(`Page ${index + 1} of ${slices.length}`, pageWidth - PAGE_MARGIN_X_MM, pageNumberY, {
      align: 'right',
    });
  });

  return pdf.output('blob');
}

/**
 * Render the MindQ Report off-screen and produce a PDF blob.
 *
 * @param {Record<string, any>} data Report payload from `/report-data`.
 * @returns {Promise<{ blob: Blob, filename: string }>}
 */
export async function renderReportPdf(data) {
  if (!data) throw new Error('Report data unavailable');
  const [logoSrc, fontCss] = await Promise.all([
    inlineLogo(data.company_logo_url),
    inlinedReportFontCss().catch((err) => {
      // Ink-free cut snapping still prevents sliced text without embedded fonts.
      console.warn('mindq_report_font_inline_failed', err);
      return null;
    }),
  ]);

  const host = document.createElement('div');
  host.setAttribute('aria-hidden', 'true');
  host.style.cssText =
    `position:fixed;left:0;top:0;width:${REPORT_WIDTH_PX}px;opacity:1;visibility:visible;` +
    'pointer-events:none;z-index:-1;background:#ffffff;';
  document.body.appendChild(host);

  const root = createRoot(host);
  try {
    flushSync(() => {
      root.render(createElement(MindQReport, { data, logoSrc }));
    });
    await ensureReportFontsLoaded();
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });

    const element = host.querySelector('.mindq-report');
    if (!(element instanceof HTMLElement)) {
      throw new Error('Report layout failed to render before PDF capture');
    }
    if (!(element.textContent || '').trim()) {
      throw new Error('Report content is empty; scoring data may still be loading');
    }

    const widthPx = Math.max(element.scrollWidth || REPORT_WIDTH_PX, REPORT_WIDTH_PX);
    const heightPx = Math.max(element.scrollHeight || 0, 200);
    const scale = Math.min(2, MAX_CANVAS_HEIGHT_PX / (heightPx + 120));
    const layout = measureReportLayout(element);
    const footerMarkup = footerHtmlForPdf(element, fontCss);
    const footerHeightPx = layout.footer ? Math.ceil(layout.footer.bottom - layout.footer.top) : 0;
    const [canvas, footerRaw] = await Promise.all([
      // Slack below the measured height so residual metric drift is never clipped.
      rasterizeReportHtml(reportHtmlForPdf(element, fontCss), widthPx, heightPx + 120, scale),
      footerMarkup && footerHeightPx > 0
        ? rasterizeReportHtml(footerMarkup, widthPx, footerHeightPx + 48, scale)
        : Promise.resolve(null),
    ]);
    const footerCanvas = footerRaw
      ? cropCanvas(footerRaw, scale, 0, Math.max(1, paintedHeight(footerRaw, scale) + 2))
      : null;
    return {
      blob: canvasToPdfBlob(canvas, footerCanvas, scale, widthPx, layout),
      filename: reportFilename(data.candidate_full_name),
    };
  } finally {
    root.unmount();
    host.remove();
  }
}

/**
 * Trigger a browser download for a blob.
 *
 * @param {Blob} blob
 * @param {string} filename
 */
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Fetch report data and download `MindQ Report - ${candidateFullName}.pdf`.
 *
 * @param {() => Promise<Record<string, any>>} fetchReportData
 * @returns {Promise<void>}
 */
export async function downloadMindQReport(fetchReportData) {
  const data = await fetchReportData();
  const { blob, filename } = await renderReportPdf(data);
  saveBlob(blob, filename);
}
