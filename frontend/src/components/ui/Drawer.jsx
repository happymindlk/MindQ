import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';

/**
 * Right-side slide-over for record drill-downs.
 */
export default function Drawer({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  widthClass = 'max-w-md',
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-canvas/70 transition-opacity duration-200 data-[state=open]:opacity-100 data-[state=closed]:opacity-0" />
        <Dialog.Content
          className={`
            fixed inset-y-0 right-0 z-50 flex w-full ${widthClass} flex-col
            bg-surface border-l border-border
            transition-transform duration-200 ease-out
            data-[state=open]:translate-x-0 data-[state=closed]:translate-x-full
            focus:outline-none
          `}
        >
          <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-border shrink-0">
            <div className="min-w-0">
              <Dialog.Title className="text-sm font-semibold text-foreground truncate">
                {title}
              </Dialog.Title>
              {description && (
                <Dialog.Description className="text-xs text-muted mt-0.5">
                  {description}
                </Dialog.Description>
              )}
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="p-1 rounded-md text-muted hover:text-foreground hover:bg-surface-raised focus-visible:ring-2 focus-visible:ring-primary shrink-0"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-4 text-sm">{children}</div>
          {footer && (
            <div className="shrink-0 border-t border-border px-4 py-3 bg-surface-raised/40 flex flex-wrap gap-2 justify-end">
              {footer}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
