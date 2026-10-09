import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useToast } from '../../components/ui/useToast';
import { buildReportsZip } from './build-reports-zip';
import { saveBlob } from './render-report-pdf';
import { reportsZipFilename } from './report-filename';
import { isReportReady } from './report-readiness';

/**
 * Bulk-download every completed MindQ Report in a package as one zip.
 *
 * @param {object} options
 * @param {string} options.packageTitle
 * @param {Array<{ candidate_id: string, name?: string, status?: string, report_available?: boolean }>} options.candidates
 * @param {(candidateId: string) => Promise<Record<string, any>>} options.fetchReportData
 */
export function useBulkReportDownload({ packageTitle, candidates, fetchReportData }) {
  const { toast } = useToast();
  const [progress, setProgress] = useState(/** @type {{ done: number, total: number } | null} */ (null));
  const controllerRef = useRef(/** @type {AbortController | null} */ (null));

  const ready = useMemo(() => candidates.filter(isReportReady), [candidates]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const start = useCallback(async () => {
    if (controllerRef.current || ready.length === 0) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setProgress({ done: 0, total: ready.length });
    try {
      const { blob, succeeded, failures } = await buildReportsZip({
        candidates: ready,
        fetchReportData,
        onProgress: setProgress,
        signal: controller.signal,
      });
      saveBlob(blob, reportsZipFilename(packageTitle));
      if (failures.length > 0) {
        toast({
          title: `${succeeded} of ${ready.length} reports downloaded`,
          description: `Skipped: ${failures.map((f) => f.name).join(', ')}. Retry these individually.`,
          variant: 'warning',
          duration: 8000,
        });
      } else {
        toast({
          title: 'Reports ready',
          description: `${succeeded} MindQ ${succeeded === 1 ? 'Report' : 'Reports'} bundled into one zip.`,
          variant: 'success',
        });
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        toast({
          title: 'Bulk download failed',
          description: err instanceof Error ? err.message : 'Could not generate reports.',
          variant: 'error',
        });
      }
    } finally {
      controllerRef.current = null;
      setProgress(null);
    }
  }, [fetchReportData, packageTitle, ready, toast]);

  return { start, progress, readyCount: ready.length, running: progress !== null };
}
