import React from 'react';

const gridCols = {
  1: 'sm:grid-cols-1',
  2: 'sm:grid-cols-2',
  3: 'sm:grid-cols-3',
  4: 'sm:grid-cols-4',
};

/**
 * Dense KPI strip using 1px separators instead of nested cards.
 */
export default function MetricStrip({ items = [], className = '' }) {
  const count = Math.min(Math.max(items.length, 1), 4);

  return (
    <div
      className={`
        grid grid-cols-1 divide-y divide-slate-200 dark:divide-neutral-800
        ${gridCols[count]} sm:divide-y-0 sm:divide-x
        rounded-lg border border-slate-200 dark:border-neutral-800 bg-surface overflow-hidden
        ${className}
      `}
    >
      {items.map((item) => (
        <div key={item.label} className="px-4 py-3 min-w-0">
          <p className="metric-label">{item.label}</p>
          <p
            className={`mt-1 text-2xl font-semibold tracking-tight tabular-data ${
              item.tone === 'success'
                ? 'text-emerald-600 dark:text-emerald-400'
                : item.tone === 'warning'
                  ? 'text-amber-600 dark:text-amber-400'
                  : item.tone === 'danger'
                    ? 'text-rose-600 dark:text-rose-400'
                    : 'text-foreground'
            }`}
          >
            {item.value}
          </p>
          {item.hint && (
            <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">{item.hint}</p>
          )}
        </div>
      ))}
    </div>
  );
}
