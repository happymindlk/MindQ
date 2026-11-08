import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useToast } from '../../components/ui/useToast';
import { clientApi } from '../../lib/clientApi';
import { isReportReady } from './report-readiness';

/**
 * Bulk-download every completed MindQ Report in a package as one server ZIP.
 *
 * @param {object} options
 * @param {string} options.packageId
 * @param {string} options.packageTitle
 * @param {Array<{ candidate_id: string, name?: string, status?: string, report_available?: boolean }>} options.candidates
 */
export function useBulkReportDownload({ packageId, packageTitle, candidates }) {
  const { toast } = useToast();
  const [running, setRunning] = useState(false);
  const controllerRef = useRef(/** @type {AbortController | null} */ (null));

  const readyCount = useMemo(() => candidates.filter(isReportReady).length, [candidates]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const start = useCallback(async () => {
    if (controllerRef.current || !packageId || readyCount === 0) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setRunning(true);
    try {
      const { succeeded, failed } = await clientApi.downloadPackageReportsZip(
        packageId,
        packageTitle,
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      if (failed > 0) {
        toast({
          title: `${succeeded} of ${succeeded + failed} reports downloaded`,
          description: 'Some reports could not be generated. Retry those candidates individually.',
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
      setRunning(false);
    }
  }, [packageId, packageTitle, readyCount, toast]);

  return { start, readyCount, running };
}
