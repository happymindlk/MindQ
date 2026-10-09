import React, { memo } from 'react';
import { Pencil } from 'lucide-react';
import { formatDate } from '../../../lib/format-date';
import CorporateLogo from './corporate-logo';

const STATUS_STYLES = {
  active:
    'bg-green-50 text-green-700 border border-green-200 dark:bg-green-950/40 dark:text-green-400 dark:border-green-900',
  inactive:
    'bg-red-50 text-red-700 border border-red-200 dark:bg-red-950/40 dark:text-red-400 dark:border-red-900',
};

function CorporateStatusPill({ active }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium ${
        active ? STATUS_STYLES.active : STATUS_STYLES.inactive
      }`}
    >
      {active ? 'Active' : 'Inactive'}
    </span>
  );
}

/**
 * Compact horizontal corporate row. Body navigates to the corporate; pencil opens the editor.
 *
 * A corporate is "Active" when it has at least one published or active package.
 *
 * @param {object} props
 * @param {import('./use-corporates').CorporateRow} props.corporate
 * @param {(corporate: import('./use-corporates').CorporateRow) => void} props.onOpen
 * @param {(corporate: import('./use-corporates').CorporateRow) => void} props.onEdit
 */
function CorporateCard({ corporate, onOpen, onEdit }) {
  const isActive = (corporate.package_count ?? 0) > 0;
  const members = corporate.candidate_count ?? 0;

  const handleKeyDown = (event) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onOpen(corporate);
    }
  };

  return (
    <div
      role="link"
      tabIndex={0}
      aria-label={`Open ${corporate.name}`}
      onClick={() => onOpen(corporate)}
      onKeyDown={handleKeyDown}
      className="group h-24 flex items-center gap-4 px-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 cursor-pointer transition-colors duration-150 ease-out hover:border-indigo-500/60 hover:bg-slate-50 dark:hover:bg-slate-800/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
    >
      <CorporateLogo name={corporate.name} logoUrl={corporate.logo_url} size="lg" />

      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate">
          {corporate.name}
        </p>
        <p
          className={`mt-1 text-xs truncate ${
            corporate.contact_email
              ? 'text-slate-500 dark:text-slate-400'
              : 'text-slate-400 dark:text-slate-500 italic'
          }`}
        >
          {corporate.contact_email || 'No HR email'}
        </p>
      </div>

      <div className="flex flex-col items-end justify-center gap-1 shrink-0">
        <div className="flex items-center gap-1">
          <CorporateStatusPill active={isActive} />
          <button
            type="button"
            aria-label={`Edit ${corporate.name}`}
            onClick={(event) => {
              event.stopPropagation();
              onEdit(corporate);
            }}
            onKeyDown={(event) => event.stopPropagation()}
            className="p-1.5 rounded-md text-slate-400 transition-colors duration-150 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
        </div>
        <p className="tabular-data text-xs text-slate-500 dark:text-slate-400">
          Created {formatDate(corporate.created_at)}
        </p>
        <p className="tabular-data text-xs font-medium text-slate-700 dark:text-slate-300">
          {members} {members === 1 ? 'Member' : 'Members'}
        </p>
      </div>
    </div>
  );
}

export default memo(CorporateCard);
