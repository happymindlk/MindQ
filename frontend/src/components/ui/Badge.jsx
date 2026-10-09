import React from 'react';

const NEUTRAL =
  'bg-slate-100 text-slate-600 border border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700';

const variants = {
  success:
    'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20',
  completed:
    'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20',
  warning:
    'bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20',
  pending:
    'bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20',
  draft:
    'bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20',
  info: 'bg-blue-500/10 text-blue-700 dark:text-blue-400 border border-blue-500/20',
  active: 'bg-blue-500/10 text-blue-700 dark:text-blue-400 border border-blue-500/20',
  scoring: 'bg-blue-500/10 text-blue-700 dark:text-blue-400 border border-blue-500/20',
  error: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border border-rose-500/20',
  danger: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border border-rose-500/20',
  indigo:
    'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300 dark:border dark:border-indigo-800',
  facet:
    'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300 dark:border dark:border-indigo-800',
  neutral: NEUTRAL,
  muted: NEUTRAL,
  archived: NEUTRAL,
  locked: NEUTRAL,
};

const dotColors = {
  success: 'bg-emerald-400',
  completed: 'bg-emerald-400',
  warning: 'bg-amber-400',
  pending: 'bg-amber-400',
  draft: 'bg-amber-400',
  error: 'bg-rose-400',
  danger: 'bg-rose-400',
  info: 'bg-blue-400',
  active: 'bg-blue-400',
  scoring: 'bg-blue-400',
  indigo: 'bg-indigo-500',
  facet: 'bg-indigo-500',
  neutral: 'bg-neutral-400',
  muted: 'bg-neutral-400',
  archived: 'bg-neutral-400',
  locked: 'bg-neutral-400',
};

const pulseVariants = new Set(['success', 'completed']);

/**
 * Status badge with semantic variants for Admin and Client views.
 *
 * @param {object} props
 * @param {React.ReactNode} props.children
 * @param {string} [props.variant='info']
 * @param {boolean} [props.showDot=false]
 * @param {string} [props.className='']
 */
export default function Badge({ children, variant = 'info', showDot = false, className = '' }) {
  const key = variants[variant] ? variant : 'info';
  const pulse = showDot && pulseVariants.has(key);

  return (
    <span
      className={`
        inline-flex items-center gap-1.5 px-2.5 py-0.5 text-xs font-medium rounded-full
        ${variants[key]}
        ${className}
      `}
    >
      {showDot && (
        <span
          className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColors[key] ?? dotColors.info} ${
            pulse ? 'animate-pulse' : ''
          }`}
        />
      )}
      {children}
    </span>
  );
}
