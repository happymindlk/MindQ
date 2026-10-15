import React, { memo } from 'react';
import { ChevronDown } from 'lucide-react';
import CandidateShareBanner from './candidate-share-banner';
import CandidateTable from './candidate-table';
import DownloadAllReportsButton from '../../features/mindq-report/download-all-reports-button';
import { clientApi } from '../../lib/clientApi';

/**
 * @param {{ pkg: object, open: boolean, onToggle: (id: string) => void, companyName: string }} props
 */
function PackageAccordion({ pkg, open, onToggle, companyName }) {
  const ratio = pkg.total_invited ? pkg.total_completed / pkg.total_invited : 0;
  const panelId = `package-panel-${pkg.id}`;

  return (
    <li className="overflow-hidden rounded-lg border border-border bg-surface">
      <button
        type="button"
        onClick={() => onToggle(pkg.id)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-center gap-4 px-4 py-3 text-left transition-colors hover:bg-surface-raised/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-600"
      >
        <ChevronDown
          aria-hidden="true"
          className={`h-4 w-4 shrink-0 text-muted transition-transform duration-200 ${open ? '' : '-rotate-90'}`}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground">{pkg.title}</p>
          <p className="truncate text-xs text-muted">{pkg.target_role || 'No target role'}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <div
            className="hidden h-1.5 w-24 overflow-hidden rounded-full bg-surface-raised sm:block"
            role="presentation"
          >
            <div className="h-full rounded-full bg-indigo-600" style={{ width: `${Math.round(ratio * 100)}%` }} />
          </div>
          <span className="text-xs tabular-nums text-foreground">
            <span className="font-semibold text-foreground">{pkg.total_completed}</span>
            {' / '}
            {pkg.total_invited} Completed
          </span>
        </div>
      </button>

      <div
        id={panelId}
        className={`grid transition-[grid-template-rows] duration-300 ease-out ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
      >
        <div className="min-h-0 overflow-hidden" inert={open ? undefined : ''}>
          <div className="space-y-3 border-t border-border p-4">
            <CandidateShareBanner pkg={pkg} companyName={companyName} />
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-[11px] font-medium uppercase tracking-wider text-muted">
                Candidate Roster
              </h3>
              <DownloadAllReportsButton
                packageTitle={pkg.title}
                candidates={pkg.candidates}
                fetchReportData={clientApi.getReportData}
              />
            </div>
            <CandidateTable candidates={pkg.candidates} />
          </div>
        </div>
      </div>
    </li>
  );
}

export default memo(PackageAccordion);
