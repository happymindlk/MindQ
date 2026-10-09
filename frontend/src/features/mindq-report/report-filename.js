import { REPORT_TITLE } from './report-copy';

const ILLEGAL_FILENAME_CHARS = /[<>:"/\\|?*\u0000-\u001f]+/g;
const MAX_NAME_LENGTH = 120;

/**
 * Strip characters that Windows/macOS/zip tooling reject while keeping spaces
 * and diacritics so the filename still reads as the candidate's real name.
 *
 * @param {string | null | undefined} value
 * @param {string} fallback
 * @returns {string}
 */
export function sanitizeFilenamePart(value, fallback = 'Candidate') {
  const cleaned = String(value ?? '')
    .replace(ILLEGAL_FILENAME_CHARS, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[. ]+$/, '')
    .slice(0, MAX_NAME_LENGTH)
    .trim();
  return cleaned || fallback;
}

/**
 * @param {string | null | undefined} candidateName
 * @returns {string} `MindQ Report - [Candidate Full Name].pdf`
 */
export function reportFilename(candidateName) {
  return `${REPORT_TITLE} - ${sanitizeFilenamePart(candidateName)}.pdf`;
}

/**
 * @param {string | null | undefined} packageTitle
 * @returns {string}
 */
export function reportsZipFilename(packageTitle) {
  return `MindQ Reports - ${sanitizeFilenamePart(packageTitle, 'Assessment Suite')}.zip`;
}

/**
 * Disambiguate duplicate names inside a zip (two candidates named "Jane Doe").
 * Mutates `used` so successive calls stay unique.
 *
 * @param {string} filename
 * @param {Set<string>} used Lower-cased names already taken.
 * @returns {string}
 */
export function uniqueFilename(filename, used) {
  const dot = filename.lastIndexOf('.');
  const stem = dot > 0 ? filename.slice(0, dot) : filename;
  const ext = dot > 0 ? filename.slice(dot) : '';
  let candidate = filename;
  let n = 2;
  while (used.has(candidate.toLowerCase())) {
    candidate = `${stem} (${n})${ext}`;
    n += 1;
  }
  used.add(candidate.toLowerCase());
  return candidate;
}
