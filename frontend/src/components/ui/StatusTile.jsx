import React, { useEffect, useState } from 'react';
import Badge from './Badge';
import { ArrowRight, CheckCircle, Clock, FileText, Lock } from 'lucide-react';
import { normalizeModuleStatus } from '../../features/candidate-dashboard/module-status';
import {
  computeServerOffsetMs,
  remainingFromDeadline,
} from '../../features/assessment-runner/use-server-timer';
import { formatClock } from '../../features/assessment-runner/use-module-timer';

/**
 * Compact assessment status tile for the candidate dashboard.
 *
 * @param {object} props
 * @param {string} props.title
 * @param {string | null} [props.description]
 * @param {string} props.status Raw or normalized progress status.
 * @param {() => void} [props.onClick]
 * @param {() => void} [props.onPrefetch] Warm the module payload on hover/focus.
 * @param {string | null} [props.lockedReason] When set, the tile cannot be launched and shows why.
 * @param {string | null} [props.durationLabel] Optional duration badge (e.g. `⏱ 4m 30s`).
 * @param {string | null} [props.expiresAt] ISO display deadline for in-progress countdown.
 * @param {string | null} [props.serverNow] ISO server clock for offset sync.
 * @param {number | null} [props.remainingSeconds] Server seed for in-progress countdown.
 * @param {() => void} [props.onTimerExpired] Fired once when the live countdown hits zero.
 */
export default function StatusTile({
  title,
  description,
  status,
  onClick,
  onPrefetch,
  lockedReason = null,
  durationLabel = null,
  expiresAt = null,
  serverNow = null,
  remainingSeconds = null,
  onTimerExpired = null,
}) {
  const lifecycle = normalizeModuleStatus(status);
  const isCompleted = lifecycle === 'completed';
  const isInProgress = lifecycle === 'in_progress';
  const isLocked = !isCompleted && Boolean(lockedReason);

  const [liveRemaining, setLiveRemaining] = useState(() => {
    if (!isInProgress) return null;
    if (expiresAt) {
      return remainingFromDeadline(expiresAt, computeServerOffsetMs(serverNow));
    }
    return typeof remainingSeconds === 'number' ? Math.max(0, remainingSeconds) : null;
  });

  const timedOut = isInProgress && liveRemaining !== null && liveRemaining <= 0;
  const interactive =
    !isCompleted && !isLocked && !timedOut && typeof onClick === 'function';

  useEffect(() => {
    if (!isInProgress) {
      setLiveRemaining(null);
      return undefined;
    }

    let expiredNotified = false;
    const notifyExpired = () => {
      if (expiredNotified || typeof onTimerExpired !== 'function') return;
      expiredNotified = true;
      onTimerExpired();
    };

    if (expiresAt) {
      const offset = computeServerOffsetMs(serverNow);
      const tick = () => {
        const left = remainingFromDeadline(expiresAt, offset);
        setLiveRemaining(left);
        if (left !== null && left <= 0) notifyExpired();
      };
      tick();
      const id = window.setInterval(tick, 1000);
      const onVisible = () => {
        if (document.visibilityState === 'visible') tick();
      };
      document.addEventListener('visibilitychange', onVisible);
      window.addEventListener('focus', tick);
      return () => {
        window.clearInterval(id);
        document.removeEventListener('visibilitychange', onVisible);
        window.removeEventListener('focus', tick);
      };
    }

    if (typeof remainingSeconds === 'number' && Number.isFinite(remainingSeconds)) {
      const deadlineMs = Date.now() + Math.max(0, remainingSeconds) * 1000;
      const tick = () => {
        const left = Math.max(0, Math.ceil((deadlineMs - Date.now()) / 1000));
        setLiveRemaining(left);
        if (left <= 0) notifyExpired();
      };
      tick();
      const id = window.setInterval(tick, 1000);
      const onVisible = () => {
        if (document.visibilityState === 'visible') tick();
      };
      document.addEventListener('visibilitychange', onVisible);
      window.addEventListener('focus', tick);
      return () => {
        window.clearInterval(id);
        document.removeEventListener('visibilitychange', onVisible);
        window.removeEventListener('focus', tick);
      };
    }

    setLiveRemaining(null);
    return undefined;
  }, [isInProgress, expiresAt, serverNow, remainingSeconds, onTimerExpired]);

  const icon = isCompleted || timedOut ? (
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
  ) : timedOut ? (
    <Badge variant="completed" showDot>
      Time Up
    </Badge>
  ) : isInProgress ? (
    <Badge variant="active" showDot>
      In Progress
    </Badge>
  ) : (
    <Badge variant="neutral">Not started</Badge>
  );

  const showLiveCountdown = isInProgress && liveRemaining != null;

  return (
    <div
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? onClick : undefined}
      onPointerEnter={interactive && onPrefetch ? onPrefetch : undefined}
      onFocus={interactive && onPrefetch ? onPrefetch : undefined}
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
        ${isInProgress && !isLocked && !timedOut ? 'border-blue-500/40' : ''}
        ${isCompleted || timedOut ? 'border-emerald-500/20' : ''}
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
        {showLiveCountdown ? (
          <span
            role="timer"
            aria-live={timedOut ? 'assertive' : 'off'}
            aria-label="Time remaining"
            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-mono text-xs font-semibold tabular-nums ${
              timedOut
                ? 'border-danger/40 bg-danger/10 text-danger'
                : 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-300'
            }`}
          >
            <Clock className="h-3.5 w-3.5 shrink-0" aria-hidden />
            {timedOut ? '0:00' : `Time remaining: ${formatClock(liveRemaining)}`}
          </span>
        ) : durationLabel ? (
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
          {timedOut && (
            <span className="cursor-not-allowed text-xs font-medium text-slate-400 dark:text-slate-500">
              Time Up — answers locked
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
