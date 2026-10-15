import React, { memo } from 'react';
import { FolderDown, Loader2 } from 'lucide-react';
import { useBulkReportDownload } from './use-bulk-report-download';

/**
 * @param {{
 *   packageTitle: string,
 *   candidates: Array<object>,
 *   fetchReportData: (candidateId: string) => Promise<Record<string, any>>,
 * }} props
 */
function DownloadAllReportsButton({ packageTitle, candidates, fetchReportData }) {
  const { start, progress, readyCount, running } = useBulkReportDownload({
    packageTitle,
    candidates,
    fetchReportData,
  });
  const disabled = running || readyCount === 0;

  return (
    <button
      type="button"
      onClick={start}
      disabled={disabled}
      aria-busy={running}
      title={
        readyCount === 0
          ? 'Available once at least one candidate completes all assessments'
          : `Bundle ${readyCount} completed ${readyCount === 1 ? 'report' : 'reports'} into one .zip`
      }
      className="inline-flex h-8 items-center gap-2 rounded-md border border-border bg-surface px-3 text-xs font-medium text-foreground transition-colors hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas disabled:cursor-not-allowed disabled:text-muted disabled:hover:bg-surface"
    >
      {running ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
      ) : (
        <FolderDown className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      <span aria-live="polite">
        {running && progress
          ? `Preparing ${progress.done} of ${progress.total}…`
          : 'Download All Reports'}
      </span>
      {!running && readyCount > 0 && (
        <span className="rounded bg-surface-raised px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-muted">
          {readyCount}
        </span>
      )}
    </button>
  );
}

export default memo(DownloadAllReportsButton);
