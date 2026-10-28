import React, { memo } from 'react';
import { Link } from 'react-router-dom';
import { CalendarClock, Pencil, Send, Trash2, Users } from 'lucide-react';
import Badge from '../../../components/ui/Badge';
import Button from '../../../components/ui/Button';
import DeadlineLabel from '../../../features/package-schedule/deadline-label';

const STATUS_BADGE = {
  draft: { variant: 'draft', label: 'Draft' },
  published: { variant: 'success', label: 'Published' },
  archived: { variant: 'neutral', label: 'Archived' },
};

const secondaryLinkClass =
  'inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md text-xs font-medium text-slate-600 border border-slate-200 transition-colors duration-150 hover:text-slate-900 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7048E2] dark:text-slate-300 dark:border-slate-700 dark:hover:text-slate-100 dark:hover:bg-slate-800';

function Metric({ label, value }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="mt-1 font-display text-2xl font-bold tabular-data text-slate-900 dark:text-slate-100">{value}</dd>
    </div>
  );
}

/**
 * One package on the corporate history page.
 *
 * @param {object} props
 * @param {import('./use-corporate-packages').CorporatePackage} props.pkg
 * @param {string} props.corporateId
 * @param {(pkg: import('./use-corporate-packages').CorporatePackage) => void} props.onShare
 * @param {(pkg: import('./use-corporate-packages').CorporatePackage) => void} props.onExtendDeadline
 * @param {(pkg: import('./use-corporate-packages').CorporatePackage) => void} [props.onDelete]
 */
function CorporatePackageCard({ pkg, corporateId, onShare, onExtendDeadline, onDelete }) {
  const badge = STATUS_BADGE[pkg.status] ?? STATUS_BADGE.draft;

  return (
    <article className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-display text-sm font-bold text-slate-900 dark:text-slate-100">{pkg.title}</h3>
          <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">
            {pkg.target_role || 'No target role'}
          </p>
          <DeadlineLabel closeTime={pkg.close_time} className="mt-1" />
        </div>
        <div className="flex items-start gap-1 shrink-0">
          <Badge variant={badge.variant} showDot>
            {badge.label}
          </Badge>
          {onDelete && pkg.status !== 'archived' && (
            <button
              type="button"
              aria-label={`Delete ${pkg.title}`}
              title={`Delete ${pkg.title}`}
              onClick={() => onDelete(pkg)}
              className="rounded-md p-1.5 text-slate-500 transition-colors duration-150 hover:bg-rose-500/10 hover:text-rose-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500 dark:text-slate-400"
            >
              <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
            </button>
          )}
        </div>
      </header>

      <dl className="grid grid-cols-2 gap-4">
        <Metric label="Invited" value={pkg.invited_count} />
        <Metric label="Completed" value={pkg.completed_count} />
      </dl>

      <div className="mt-auto flex flex-wrap items-center gap-2">
        {pkg.status === 'published' && (
          <Button variant="accent" size="sm" onClick={() => onShare(pkg)}>
            <Send className="w-3.5 h-3.5" aria-hidden="true" />
            Share Assessment
          </Button>
        )}
        {pkg.status === 'published' && (
          <button
            type="button"
            className={secondaryLinkClass}
            onClick={() => onExtendDeadline(pkg)}
            aria-label={`Extend deadline for ${pkg.title}`}
          >
            <CalendarClock className="w-3.5 h-3.5" aria-hidden="true" />
            Extend deadline
          </button>
        )}
        {pkg.status === 'draft' && (
          <Link to={`/admin/packages/edit/${pkg.id}`} className={secondaryLinkClass}>
            <Pencil className="w-3.5 h-3.5" aria-hidden="true" />
            Continue editing
          </Link>
        )}
        {pkg.status !== 'draft' && (
          <Link to={`/admin/history/${corporateId}/${pkg.id}`} className={secondaryLinkClass}>
            <Users className="w-3.5 h-3.5" aria-hidden="true" />
            Candidates
          </Link>
        )}
      </div>
    </article>
  );
}

export default memo(CorporatePackageCard);
