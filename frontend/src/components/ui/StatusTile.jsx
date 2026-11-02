import React from 'react';
import Badge from './Badge';
import { ArrowRight, CheckCircle, Clock, FileText, Lock } from 'lucide-react';
import { normalizeModuleStatus } from '../../features/candidate-dashboard/module-status';

/**
 * Compact assessment status tile for the candidate dashboard.
 *
 * @param {object} props
 * @param {string} props.title
 * @param {string | null} [props.description]
 * @param {string} props.status Raw or normalized progress status.
 * @param {() => void} [props.onClick]
 * @param {string | null} [props.lockedReason] When set, the tile cannot be launched and shows why.
 * @param {string | null} [props.durationLabel] Optional duration badge (e.g. `⏱ 4 mins`).
 */
export default function StatusTile({
  title,
  description,
  status,
  onClick,
  lockedReason = null,
  durationLabel = null,
}) {
  const lifecycle = normalizeModuleStatus(status);
  const isCompleted = lifecycle === 'completed';
  const isInProgress = lifecycle === 'in_progress';
  const isLocked = !isCompleted && Boolean(lockedReason);
  const interactive = !isCompleted && !isLocked && typeof onClick === 'function';

  const icon = isCompleted ? (
    <CheckCircle className="h-5 w-5 text-emerald-500" />
  ) : isLocked ? (
    <Lock className="h-5 w-5" />
  ) : isInProgress ? (
    <Clock className="h-5 w-5 text-blue-400" />
  ) : (
    <FileText className="h-5 w-5" />
  );

  const badge = isCompleted ? (
    <Badge variant="completed" showDot>
      Completed
    </Badge>
  ) : isInProgress ? (
    <Badge variant="active" showDot>
      In Progress
    </Badge>
  ) : (
    <Badge variant="neutral">Not started</Badge>
  );

  return (
    <div
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? onClick : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      className={`
        flex min-h-[9.5rem] flex-col rounded-lg border border-slate-200 bg-surface p-3 dark:border-neutral-800
        ${isInProgress && !isLocked ? 'border-blue-500/40' : ''}
        ${isCompleted ? 'border-emerald-500/20' : ''}
        ${isLocked ? 'opacity-70' : ''}
        ${
          interactive
            ? 'cursor-pointer transition-colors duration-150 ease-out hover:border-neutral-400 focus-visible:ring-2 focus-visible:ring-primary dark:hover:border-neutral-700'
            : ''
        }
      `}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          {icon}
        </div>
        {durationLabel ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300">
            <Clock className="h-3.5 w-3.5 text-slate-500" aria-hidden />
            {durationLabel.replace(/^⏱\s*/, '')}
          </span>
        ) : null}
      </div>

      <div className="flex-1">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {description && (
          <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted">{description}</p>
        )}
      </div>

      <div className="mt-4 flex items-end justify-between gap-2">
        <div className="min-w-0">
          {isCompleted && (
            <span className="cursor-not-allowed text-xs font-medium text-slate-400 dark:text-slate-500">
              Completed
            </span>
          )}
          {interactive && (
            <div
              className={`flex items-center text-xs font-semibold ${
                isInProgress ? 'text-blue-600 dark:text-blue-400' : 'text-primary-text'
              }`}
            >
              {isInProgress ? 'Continue test' : 'Start test'}
              <ArrowRight className="ml-1 h-3.5 w-3.5" />
            </div>
          )}
          {isLocked && (
            <p className="flex items-center gap-1 text-xs font-medium text-muted">
              <Lock className="h-3.5 w-3.5" aria-hidden="true" />
              {lockedReason}
            </p>
          )}
        </div>
        <div className="shrink-0">{badge}</div>
      </div>
    </div>
  );
}
