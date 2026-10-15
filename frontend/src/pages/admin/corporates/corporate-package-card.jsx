import React, { memo } from 'react';
import { Link } from 'react-router-dom';
import { CalendarClock, Pencil, Send, Users } from 'lucide-react';
import Badge from '../../../components/ui/Badge';
import Button from '../../../components/ui/Button';
import DeadlineLabel from '../../../features/package-schedule/deadline-label';

const STATUS_BADGE = {
  draft: { variant: 'draft', label: 'Draft' },
  published: { variant: 'success', label: 'Published' },
  archived: { variant: 'neutral', label: 'Archived' },
};

const secondaryLinkClass =
  'inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md text-xs font-medium text-neutral-400 border border-neutral-800 transition-colors duration-150 hover:text-neutral-100 hover:bg-neutral-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-600';

function Metric({ label, value }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wider text-neutral-400">{label}</dt>
      <dd className="mt-1 text-lg font-semibold tabular-data text-foreground">{value}</dd>
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
 */
function CorporatePackageCard({ pkg, corporateId, onShare, onExtendDeadline }) {
  const badge = STATUS_BADGE[pkg.status] ?? STATUS_BADGE.draft;

  return (
    <article className="flex flex-col gap-4 rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-4">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground truncate">{pkg.title}</h3>
          <p className="mt-1 text-xs text-neutral-400 truncate">
            {pkg.target_role || 'No target role'}
          </p>
          <DeadlineLabel closeTime={pkg.close_time} className="mt-1" />
        </div>
        <Badge variant={badge.variant} showDot className="shrink-0">
          {badge.label}
        </Badge>
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
