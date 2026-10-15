import React from 'react';

const STATUS = {
  invited: {
    label: 'Invited',
    className: 'border-border bg-surface-raised text-muted',
    dot: 'bg-muted',
  },
  in_progress: {
    label: 'In Progress',
    className: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
    dot: 'bg-amber-400',
  },
  completed: {
    label: 'Completed',
    className: 'border-indigo-600/40 bg-indigo-600/10 text-indigo-700 dark:text-indigo-300',
    dot: 'bg-indigo-500',
  },
};

/** @param {{ status: 'invited' | 'in_progress' | 'completed' }} props */
export default function ClientStatusBadge({ status }) {
  const cfg = STATUS[status] ?? STATUS.invited;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${cfg.className}`}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}
