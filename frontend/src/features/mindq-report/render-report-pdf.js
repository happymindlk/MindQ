import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { jsPDF } from 'jspdf';
import MindQReport from './mindq-report';
import { safeLogoUrl } from './report-logo';
import { computePageSlices } from './pdf-pagination';
import { REPORT_TITLE } from './report-copy';
import { reportFilename } from './report-filename';
import { REPORT_WIDTH_PX } from './report-styles';

const PAGE_MARGIN_MM = 10;
const FOOTER_BAND_MM = 8;
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
 * Collect safe break offsets (block bottoms) relative to the report root.
 *
 * @param {HTMLElement} root
 * @returns {number[]}
 */
function collectBreakpoints(root) {
  const rootTop = root.getBoundingClientRect().top;
  const points = [];
  root.querySelectorAll('[data-pdf-block], tr').forEach((el) => {
    const rect = el.getBoundingClientRect();
    points.push(rect.top - rootTop, rect.bottom - rootTop);
  });
  return points;
}

/**
 * Build a paginated A4 PDF from the rasterized report.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {number} scale Canvas px per CSS px.
 * @param {number} widthPx Report width (CSS px).
 * @param {number} heightPx Report height (CSS px).
 * @param {number[]} breakpoints Safe break offsets (CSS px).
 * @returns {Blob}
 */
function canvasToPdfBlob(canvas, scale, widthPx, heightPx, breakpoints) {
  const pdf = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const usableWidth = pageWidth - PAGE_MARGIN_MM * 2;
  const usableHeight = pageHeight - PAGE_MARGIN_MM * 2 - FOOTER_BAND_MM;
  const mmPerPx = usableWidth / widthPx;
  const pageHeightPx = usableHeight / mmPerPx;

  const slices = computePageSlices(heightPx, pageHeightPx, breakpoints);
  slices.forEach((slice, index) => {
    const sliceHeightPx = slice.end - slice.start;
    const pageCanvas = document.createElement('canvas');
    pageCanvas.width = canvas.width;
    pageCanvas.height = Math.max(1, Math.round(sliceHeightPx * scale));
    const ctx = pageCanvas.getContext('2d');
    if (!ctx) throw new Error('Canvas unavailable for PDF pagination');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, pageCanvas.width, pageCanvas.height);
    ctx.drawImage(
      canvas,
      0,
      Math.round(slice.start * scale),
      canvas.width,
      pageCanvas.height,
      0,
      0,
      pageCanvas.width,
      pageCanvas.height,
    );

    if (index > 0) pdf.addPage();
    pdf.addImage(
      pageCanvas.toDataURL('image/jpeg', 0.95),
      'JPEG',
      PAGE_MARGIN_MM,
      PAGE_MARGIN_MM,
      usableWidth,
      sliceHeightPx * mmPerPx,
    );

    const footerY = pageHeight - PAGE_MARGIN_MM;
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(8);
    pdf.setTextColor(107, 114, 128);
    pdf.text(REPORT_TITLE, PAGE_MARGIN_MM, footerY);
    pdf.text(`Page ${index + 1} of ${slices.length}`, pageWidth - PAGE_MARGIN_MM, footerY, {
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
    const breakpoints = collectBreakpoints(element);
    const canvas = await rasterizeReportHtml(element.outerHTML, widthPx, heightPx, scale);
    return {
      blob: canvasToPdfBlob(canvas, scale, widthPx, heightPx, breakpoints),
      filename: reportFilename(data.candidate_name),
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
 * Fetch report data and download `MindQ Report - [Candidate Full Name].pdf`.
 *
 * @param {() => Promise<Record<string, any>>} fetchReportData
 * @returns {Promise<void>}
 */
export async function downloadMindQReport(fetchReportData) {
  const data = await fetchReportData();
  const { blob, filename } = await renderReportPdf(data);
  saveBlob(blob, filename);
}
