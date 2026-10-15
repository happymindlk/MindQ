import React from 'react';

const variants = {
  default: 'bg-surface border border-slate-200 dark:border-neutral-800',
  elevated: 'bg-surface-raised border border-slate-200 dark:border-neutral-800',
  interactive:
    'bg-surface border border-slate-200 dark:border-neutral-800 cursor-pointer transition-colors duration-150 ease-out hover:border-neutral-400 dark:hover:border-neutral-700',
  flush: 'bg-transparent border-0',
};

export default function Card({
  children,
  className = '',
  variant = 'default',
  padding = 'p-3',
  ...props
}) {
  return (
    <div
      className={`rounded-lg overflow-hidden ${variants[variant] ?? variants.default} ${padding} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
