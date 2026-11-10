import poppins300 from '@fontsource/poppins/files/poppins-latin-300-normal.woff2?url';
import poppins400 from '@fontsource/poppins/files/poppins-latin-400-normal.woff2?url';
import poppins500 from '@fontsource/poppins/files/poppins-latin-500-normal.woff2?url';
import poppins600 from '@fontsource/poppins/files/poppins-latin-600-normal.woff2?url';
import poppins700 from '@fontsource/poppins/files/poppins-latin-700-normal.woff2?url';

/**
 * Report-private family names. The SVG rasterizer used for PDF export cannot
 * reach the app's Google Fonts stylesheet, so it silently fell back to a
 * narrower system font and the measured layout no longer matched the image.
 * Binding the report to self-hosted Poppins under unique names lets the same
 * font binaries drive both measurement and rasterization — matching the
 * WeasyPrint template which also uses Poppins exclusively.
 */
export const REPORT_FONT_SANS = 'MindQ Report Sans';
export const REPORT_FONT_DISPLAY = 'MindQ Report Display';

/**
 * @typedef {{ family: string, weight: number, style: 'normal' | 'italic', url: string }} ReportFontFace
 */

/** @type {ReportFontFace[]} */
export const REPORT_FONT_FACES = [
  { family: REPORT_FONT_SANS, weight: 300, style: 'normal', url: poppins300 },
  { family: REPORT_FONT_SANS, weight: 400, style: 'normal', url: poppins400 },
  { family: REPORT_FONT_SANS, weight: 500, style: 'normal', url: poppins500 },
  { family: REPORT_FONT_SANS, weight: 600, style: 'normal', url: poppins600 },
  { family: REPORT_FONT_SANS, weight: 700, style: 'normal', url: poppins700 },
  { family: REPORT_FONT_DISPLAY, weight: 300, style: 'normal', url: poppins300 },
  { family: REPORT_FONT_DISPLAY, weight: 400, style: 'normal', url: poppins400 },
  { family: REPORT_FONT_DISPLAY, weight: 500, style: 'normal', url: poppins500 },
  { family: REPORT_FONT_DISPLAY, weight: 600, style: 'normal', url: poppins600 },
  { family: REPORT_FONT_DISPLAY, weight: 700, style: 'normal', url: poppins700 },
];

/**
 * @param {(face: ReportFontFace) => string} srcFor
 * @returns {string}
 */
function fontFaceCss(srcFor) {
  return REPORT_FONT_FACES.map(
    (face) =>
      `@font-face{font-family:"${face.family}";font-style:${face.style};font-weight:${face.weight};` +
      `font-display:block;src:url("${srcFor(face)}") format("woff2");}`,
  ).join('\n');
}

/** `@font-face` rules pointing at the bundled same-origin font files. */
export const REPORT_FONT_FACE_CSS = fontFaceCss((face) => face.url);

/**
 * Wait until every report face is decoded so layout measurement uses the
 * final glyph metrics instead of a fallback font.
 *
 * @returns {Promise<void>}
 */
export async function ensureReportFontsLoaded() {
  if (typeof document === 'undefined' || !document.fonts?.load) return;
  await Promise.all(
    REPORT_FONT_FACES.map((face) =>
      document.fonts.load(`${face.style} ${face.weight} 16px "${face.family}"`).catch((err) => {
        console.warn('mindq_report_font_load_failed', face.family, face.weight, err);
        return [];
      }),
    ),
  );
  await document.fonts.ready;
}

/**
 * @param {string} url
 * @returns {Promise<string>}
 */
async function toDataUrl(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Font fetch failed (${res.status}) for ${url}`);
  const blob = await res.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      typeof reader.result === 'string'
        ? resolve(reader.result)
        : reject(new Error('Font could not be encoded'));
    reader.onerror = () => reject(reader.error ?? new Error('Font could not be encoded'));
    reader.readAsDataURL(blob);
  });
}

/** @type {Promise<string> | null} */
let inlinedCssPromise = null;

/**
 * `@font-face` rules with the font binaries embedded as data URLs, for the
 * sandboxed SVG image that cannot load external resources. Cached per session.
 *
 * @returns {Promise<string>}
 */
export function inlinedReportFontCss() {
  if (!inlinedCssPromise) {
    inlinedCssPromise = Promise.all(REPORT_FONT_FACES.map((face) => toDataUrl(face.url)))
      .then((dataUrls) => {
        const byUrl = new Map(REPORT_FONT_FACES.map((face, i) => [face.url, dataUrls[i]]));
        return fontFaceCss((face) => byUrl.get(face.url) ?? face.url);
      })
      .catch((err) => {
        inlinedCssPromise = null;
        throw err;
      });
  }
  return inlinedCssPromise;
}
