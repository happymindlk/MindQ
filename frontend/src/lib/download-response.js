/**
 * @typedef {object} ReportDownloadResult
 * @property {boolean} isHtml True when the server fell back to HTML (WeasyPrint unavailable).
 * @property {string} synthesisStatus `X-Report-Synthesis-Status`, e.g. `ok` or `generating`.
 * @property {string} cacheState `X-Report-Cache`: `HIT`, `MISS`, `BYPASS`, or `''`.
 */

/**
 * @typedef {object} ZipDownloadResult
 * @property {number} succeeded Reports included in the ZIP (`X-Report-Zip-Count`).
 * @property {number} failed Reports skipped after a render error (`X-Report-Zip-Failed`).
 * @property {string} filename Saved attachment name.
 */

/**
 * Resolve a download filename from `Content-Disposition`, with a fallback.
 *
 * @param {Response} res
 * @param {string} fallbackFilename
 * @returns {string}
 */
export function filenameFromContentDisposition(res, fallbackFilename) {
  const disposition = res.headers.get('content-disposition') || '';
  const encodedName = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
  const asciiName = /filename="([^"]+)"/i.exec(disposition)?.[1];
  if (encodedName) return decodeURIComponent(encodedName);
  if (asciiName) return asciiName;
  return fallbackFilename;
}

/**
 * Trigger a browser download for a successful blob response.
 *
 * @param {Response} res Successful (2xx) response with a body.
 * @param {string} fallbackFilename Used when `Content-Disposition` is absent.
 * @returns {Promise<string>} The filename that was offered to the browser.
 */
export async function saveAttachmentResponse(res, fallbackFilename) {
  const blob = await res.blob();
  const filename = filenameFromContentDisposition(res, fallbackFilename);
  // Blob + anchor download — never window.open (popup blockers / CORS).
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  return filename;
}

/**
 * Save a server-rendered report response to disk and return its metadata.
 * Shared by the admin and client portals so both download the same file the
 * same way.
 *
 * @param {Response} res Successful report response.
 * @param {string} fallbackStem Filename stem used when `Content-Disposition` is absent.
 * @returns {Promise<ReportDownloadResult>}
 */
export async function saveReportResponse(res, fallbackStem) {
  const reportType = res.headers.get('x-report-type') || '';
  const isHtml = reportType === 'HTML' || (res.headers.get('content-type') || '').includes('text/html');
  await saveAttachmentResponse(res, `${fallbackStem}.${isHtml ? 'html' : 'pdf'}`);
  return {
    isHtml,
    synthesisStatus: res.headers.get('x-report-synthesis-status') || '',
    cacheState: res.headers.get('x-report-cache') || '',
  };
}
