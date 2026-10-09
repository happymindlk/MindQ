import { renderReportPdf } from './render-report-pdf';
import { uniqueFilename } from './report-filename';

/**
 * @typedef {object} ZipCandidate
 * @property {string} candidate_id
 * @property {string} [name]
 */

/**
 * @typedef {object} ZipFailure
 * @property {string} name
 * @property {string} message
 */

/**
 * Render every candidate's MindQ Report and bundle them into one zip.
 *
 * Reports render sequentially: each PDF needs an off-screen DOM host and a
 * full-size canvas, so parallel renders would multiply peak memory for no gain.
 * A single candidate failing is recorded and skipped rather than aborting the
 * batch; the batch only fails when no report could be produced.
 *
 * @param {object} options
 * @param {ZipCandidate[]} options.candidates
 * @param {(candidateId: string) => Promise<Record<string, any>>} options.fetchReportData
 * @param {(progress: { done: number, total: number }) => void} [options.onProgress]
 * @param {AbortSignal} [options.signal]
 * @param {(data: Record<string, any>) => Promise<{ blob: Blob, filename: string }>} [options.renderPdf]
 * @returns {Promise<{ blob: Blob, succeeded: number, failures: ZipFailure[] }>}
 */
export async function buildReportsZip({
  candidates,
  fetchReportData,
  onProgress,
  signal,
  renderPdf = renderReportPdf,
}) {
  if (candidates.length === 0) throw new Error('No completed reports to download');
  const { default: JSZip } = await import('jszip');
  const zip = new JSZip();
  const used = new Set();
  const failures = [];
  let succeeded = 0;

  for (let i = 0; i < candidates.length; i += 1) {
    if (signal?.aborted) throw new DOMException('Bulk download cancelled', 'AbortError');
    const candidate = candidates[i];
    try {
      const data = await fetchReportData(candidate.candidate_id);
      const { blob, filename } = await renderPdf(data);
      zip.file(uniqueFilename(filename, used), blob);
      succeeded += 1;
    } catch (err) {
      failures.push({
        name: candidate.name || candidate.candidate_id,
        message: err instanceof Error ? err.message : String(err),
      });
    }
    onProgress?.({ done: i + 1, total: candidates.length });
  }

  if (succeeded === 0) {
    throw new Error(failures[0]?.message || 'No reports could be generated');
  }
  // PDFs are already compressed; STORE avoids burning CPU for ~0% gain.
  const blob = await zip.generateAsync({ type: 'blob', compression: 'STORE' });
  return { blob, succeeded, failures };
}
