import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { jsPDF } from 'jspdf';
import MindQReport from './mindq-report';
import { safeLogoUrl } from './report-logo';
import { computePageSlices } from './pdf-pagination';
import { reportFilename } from './report-filename';
import { REPORT_WIDTH_PX } from './report-styles';

const PAGE_MARGIN_MM = 10;
const FOOTER_GAP_MM = 3;
const PAGE_NUMBER_BAND_MM = 4;
const MAX_CANVAS_HEIGHT_PX = 30000;
const MAX_LOGO_BYTES = 2 * 1024 * 1024;
const LOGO_FETCH_TIMEOUT_MS = 8000;

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

  const keepTogether = [...root.querySelectorAll('[data-pdf-block]')].map(rangeOf);
  const breakpoints = [];
  keepTogether.forEach((r) => breakpoints.push(r.top, r.bottom));
  root.querySelectorAll('[data-pdf-row], tr').forEach((el) => {
    const r = rangeOf(el);
    breakpoints.push(r.top, r.bottom);
  });

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
 * Build a paginated A4 PDF from the rasterized report, repeating the
 * branded disclaimer footer at the bottom of every page.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {number} scale Canvas px per CSS px.
 * @param {number} widthPx Report width (CSS px).
 * @param {ReportLayout} layout
 * @returns {Blob}
 */
function canvasToPdfBlob(canvas, scale, widthPx, layout) {
  const pdf = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const usableWidth = pageWidth - PAGE_MARGIN_MM * 2;
  const mmPerPx = usableWidth / widthPx;

  const footerHeightPx = layout.footer ? layout.footer.bottom - layout.footer.top : 0;
  const footerHeightMm = footerHeightPx * mmPerPx;
  const footerImage =
    layout.footer && footerHeightPx > 0
      ? cropCanvas(canvas, scale, layout.footer.top, footerHeightPx).toDataURL('image/jpeg', 0.95)
      : null;

  const usableHeight =
    pageHeight - PAGE_MARGIN_MM * 2 - footerHeightMm - FOOTER_GAP_MM - PAGE_NUMBER_BAND_MM;
  const pageHeightPx = usableHeight / mmPerPx;

  const slices = computePageSlices(layout.contentHeight, pageHeightPx, layout.breakpoints, {
    keepTogether: layout.keepTogether,
  });
  slices.forEach((slice, index) => {
    const sliceHeightPx = slice.end - slice.start;
    const pageCanvas = cropCanvas(canvas, scale, slice.start, sliceHeightPx);

    if (index > 0) pdf.addPage();
    pdf.addImage(
      pageCanvas.toDataURL('image/jpeg', 0.95),
      'JPEG',
      PAGE_MARGIN_MM,
      PAGE_MARGIN_MM,
      usableWidth,
      sliceHeightPx * mmPerPx,
    );

    const pageNumberY = pageHeight - PAGE_MARGIN_MM;
    if (footerImage) {
      pdf.addImage(
        footerImage,
        'JPEG',
        PAGE_MARGIN_MM,
        pageNumberY - PAGE_NUMBER_BAND_MM - footerHeightMm,
        usableWidth,
        footerHeightMm,
      );
    }
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(8);
    pdf.setTextColor(107, 114, 128);
    pdf.text(`Page ${index + 1} of ${slices.length}`, pageWidth - PAGE_MARGIN_MM, pageNumberY, {
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
  const logoSrc = await inlineLogo(data.company_logo_url);

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
    const scale = Math.min(2, MAX_CANVAS_HEIGHT_PX / heightPx);
    const layout = measureReportLayout(element);
    const canvas = await rasterizeReportHtml(element.outerHTML, widthPx, heightPx, scale);
    return {
      blob: canvasToPdfBlob(canvas, scale, widthPx, layout),
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
