import React from 'react';

/**
 * Dimension-matched shimmer placeholder.
 */
export default function Skeleton({ className = '', ...props }) {
  return (
    <div
      className={`animate-pulse rounded bg-slate-200/80 dark:bg-neutral-800/60 ${className}`}
      aria-hidden="true"
      {...props}
    />
  );
}

export function SkeletonTable({ rows = 6, cols = 5 }) {
  return (
    <div
      className="w-full border border-slate-200 dark:border-neutral-800 rounded-lg overflow-hidden"
      role="status"
      aria-label="Loading"
    >
      <div className="flex gap-3 px-3 py-2 bg-surface-raised border-b border-slate-200 dark:border-neutral-800">
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={`h-${i}`} className="h-3 flex-1" />
        ))}
      </div>
      <div className="divide-y divide-slate-200 dark:divide-neutral-800">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={`r-${r}`} className="flex gap-3 px-3 py-2.5">
            {Array.from({ length: cols }).map((_, c) => (
              <Skeleton key={`c-${r}-${c}`} className="h-3.5 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function SkeletonKpi({ count = 4 }) {
  return (
    <div
      className="grid grid-cols-2 lg:grid-cols-4 border border-slate-200 dark:border-neutral-800 rounded-lg overflow-hidden bg-surface"
      role="status"
      aria-label="Loading metrics"
    >
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="px-4 py-3 border-b lg:border-b-0 border-r border-slate-200 dark:border-neutral-800 last:border-r-0"
        >
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-7 w-16 mt-2" />
          <Skeleton className="h-3 w-24 mt-2" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonRows({ rows = 4 }) {
  return (
    <div
      className="rounded-lg border border-slate-200 dark:border-neutral-800 divide-y divide-slate-200 dark:divide-neutral-800 bg-surface"
      role="status"
      aria-label="Loading"
    >
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 px-3 py-2.5">
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-12" />
        </div>
      ))}
    </div>
  );
}
