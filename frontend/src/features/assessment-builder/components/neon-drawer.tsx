import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

interface NeonDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: string;
  headerExtra?: ReactNode;
  footer?: ReactNode;
  widthClass?: string;
  children: ReactNode;
}

export function NeonDrawer({
  open,
  onOpenChange,
  title,
  description,
  headerExtra,
  footer,
  widthClass = 'max-w-2xl',
  children,
}: NeonDrawerProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" />
        <Dialog.Content
          className={`fixed inset-y-0 right-0 z-40 flex w-full ${widthClass} flex-col border-l border-cyan-500/30 bg-slate-950/95 text-slate-100 shadow-[0_0_40px_rgba(6,182,212,0.15)] backdrop-blur-xl focus:outline-none`}
        >
          <header className="flex items-start justify-between gap-4 border-b border-slate-800 px-6 py-4">
            <div className="min-w-0 space-y-1">
              <Dialog.Title className="truncate text-base font-semibold text-white">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="text-xs text-slate-400">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">Details panel</Dialog.Description>
              )}
              {headerExtra}
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Close panel"
                className="rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
              >
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </header>
          <div className="flex-1 overflow-y-auto px-6 py-4">{children}</div>
          {footer && (
            <footer className="flex flex-wrap justify-end gap-2 border-t border-slate-800 bg-slate-900/60 px-6 py-4">
              {footer}
            </footer>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
