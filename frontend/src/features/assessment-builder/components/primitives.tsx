import * as Dialog from '@radix-ui/react-dialog';
import { Loader2, X } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

export type Tone = 'neutral' | 'indigo' | 'cyan' | 'violet' | 'emerald' | 'amber' | 'danger';

const PILL_TONES: Record<Tone, string> = {
  neutral: 'border-slate-200 bg-slate-100 text-slate-600 dark:border-slate-700/80 dark:bg-slate-800/60 dark:text-slate-300',
  indigo: 'border-transparent bg-indigo-50 text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-300',
  cyan: 'border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-500/40 dark:bg-cyan-500/10 dark:text-cyan-300',
  violet: 'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-500/40 dark:bg-violet-500/10 dark:text-violet-300',
  emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-300',
  amber: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-300',
  danger: 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-300',
};

export function Pill({
  tone = 'neutral',
  icon,
  children,
  className = '',
  title,
}: {
  tone?: Tone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4 whitespace-nowrap ${PILL_TONES[tone]} ${className}`}
    >
      {icon}
      {children}
    </span>
  );
}

type ButtonVariant = 'primary' | 'violet' | 'ghost' | 'danger' | 'outline';

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-cyan-500 text-slate-950 hover:bg-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.35)] focus-visible:ring-cyan-300',
  violet:
    'bg-violet-500 text-white hover:bg-violet-400 shadow-[0_0_12px_rgba(139,92,246,0.35)] focus-visible:ring-violet-300',
  ghost: 'bg-transparent text-slate-300 hover:bg-slate-800/80 hover:text-white focus-visible:ring-cyan-500/60',
  outline:
    'border border-slate-700 bg-slate-900/60 text-slate-200 hover:border-cyan-500/50 hover:text-white focus-visible:ring-cyan-500/60',
  danger:
    'bg-rose-500/90 text-white hover:bg-rose-500 shadow-[0_0_12px_rgba(244,63,94,0.35)] focus-visible:ring-rose-300',
};

export function NeonButton({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  children,
  className = '',
  type = 'button',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: 'sm' | 'md';
  loading?: boolean;
}) {
  const sizing = size === 'sm' ? 'h-8 px-3 text-xs' : 'h-10 px-4 text-sm';
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none ${sizing} ${BUTTON_VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Switch({
  id,
  checked,
  onChange,
  label,
  description,
  disabled = false,
}: {
  id: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-slate-100">
          {label}
        </label>
        {description && <p className="mt-0.5 text-xs text-slate-400">{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50 ${
          checked
            ? 'border-cyan-400/60 bg-cyan-500/30 shadow-[0_0_12px_rgba(6,182,212,0.35)]'
            : 'border-slate-700 bg-slate-800'
        }`}
      >
        <span
          aria-hidden
          className={`inline-block h-4 w-4 rounded-full transition-transform ${
            checked ? 'translate-x-6 bg-cyan-300' : 'translate-x-1 bg-slate-400'
          }`}
        />
      </button>
    </div>
  );
}

export function FieldLabel({ htmlFor, children, hint }: { htmlFor: string; children: ReactNode; hint?: string }) {
  return (
    <div className="mb-1 flex items-baseline justify-between gap-2">
      <label htmlFor={htmlFor} className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        {children}
      </label>
      {hint && <span className="text-[11px] text-slate-500">{hint}</span>}
    </div>
  );
}

export const inputClass =
  'w-full rounded-lg border border-slate-700/80 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 transition-colors focus:outline-none focus:border-cyan-500/60 focus:shadow-[0_0_12px_rgba(6,182,212,0.25)] disabled:cursor-not-allowed disabled:opacity-60';

const DIALOG_TONES: Record<'cyan' | 'violet' | 'danger', string> = {
  cyan: 'border-cyan-500/40 shadow-[0_0_32px_rgba(6,182,212,0.18)]',
  violet: 'border-violet-500/40 shadow-[0_0_32px_rgba(139,92,246,0.2)]',
  danger: 'border-rose-500/50 shadow-[0_0_32px_rgba(244,63,94,0.25)]',
};

export function NeonDialog({
  open,
  onOpenChange,
  title,
  description,
  tone = 'cyan',
  widthClass = 'max-w-lg',
  children,
  footer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  tone?: 'cyan' | 'violet' | 'danger';
  widthClass?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" />
        <Dialog.Content
          className={`fixed left-1/2 top-1/2 z-50 flex max-h-[90vh] w-[calc(100vw-2rem)] ${widthClass} -translate-x-1/2 -translate-y-1/2 flex-col rounded-2xl border bg-slate-950/95 text-slate-100 backdrop-blur-xl focus:outline-none ${DIALOG_TONES[tone]}`}
        >
          <div className="flex items-start justify-between gap-4 border-b border-slate-800 px-6 py-4">
            <div className="min-w-0">
              <Dialog.Title className="text-base font-semibold text-white">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="mt-1 text-xs text-slate-400">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">{title}</Dialog.Description>
              )}
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Close"
                className="rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
              >
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-4">{children}</div>
          {footer && (
            <div className="flex flex-wrap justify-end gap-2 border-t border-slate-800 bg-slate-900/60 px-6 py-4">
              {footer}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
