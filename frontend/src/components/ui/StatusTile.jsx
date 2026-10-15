import React from 'react';
import Badge from './Badge';
import { ArrowRight, CheckCircle, Clock, FileText, Lock } from 'lucide-react';

/**
 * Compact assessment status tile for the candidate dashboard.
 *
 * @param {object} props
 * @param {string} props.title
 * @param {string | null} [props.description]
 * @param {'not_started' | 'in_progress' | 'completed'} props.status
 * @param {() => void} [props.onClick]
 * @param {string | null} [props.lockedReason] When set, the tile cannot be launched and shows why.
 */
export default function StatusTile({ title, description, status, onClick, lockedReason = null }) {
  const isCompleted = status === 'completed';
  const isInProgress = status === 'in_progress';
  const isLocked = !isCompleted && Boolean(lockedReason);
  const interactive = !isCompleted && !isLocked && typeof onClick === 'function';

  const icon = isCompleted ? (
    <CheckCircle className="w-5 h-5 text-success" />
  ) : isLocked ? (
    <Lock className="w-5 h-5 text-muted" />
  ) : isInProgress ? (
    <Clock className="w-5 h-5 text-blue-400" />
  ) : (
    <FileText className="w-5 h-5 text-muted" />
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
    <Badge variant="pending">Not started</Badge>
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
        rounded-lg border border-slate-200 dark:border-neutral-800 bg-surface p-3
        ${isInProgress && !isLocked ? 'border-blue-500/40' : ''}
        ${isLocked ? 'opacity-70' : ''}
        ${
          interactive
            ? 'cursor-pointer transition-colors duration-150 ease-out hover:border-neutral-400 dark:hover:border-neutral-700 focus-visible:ring-2 focus-visible:ring-primary'
            : ''
        }
      `}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-surface-raised">
          {icon}
        </div>
        {badge}
      </div>

      <div className="mt-3">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {description && (
          <p className="mt-1 text-xs text-muted line-clamp-2 leading-relaxed">{description}</p>
        )}
      </div>

      {interactive && (
        <div className="mt-4 flex items-center text-xs font-medium text-primary-text">
          {isInProgress ? 'Continue test' : 'Start test'}
          <ArrowRight className="w-3.5 h-3.5 ml-1" />
        </div>
      )}
      {isLocked && (
        <p className="mt-4 flex items-center gap-1 text-xs font-medium text-muted">
          <Lock className="w-3.5 h-3.5" aria-hidden="true" />
          {lockedReason}
        </p>
      )}
    </div>
  );
}
