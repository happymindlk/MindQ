/**
 * @param {{ status?: string, report_available?: boolean }} candidate
 * @returns {boolean}
 */
export function isReportReady(candidate) {
  return candidate?.status === 'completed' && Boolean(candidate?.report_available);
}
