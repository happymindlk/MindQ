import React, { useEffect } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';

/**
 * Centered modal dialog. Prefer Drawer for record drill-downs.
 */
export default function Modal({ isOpen, onClose, title, children, actions, contentClassName = '' }) {
  useEffect(() => {
    if (!isOpen) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [isOpen]);

  return (
    <Dialog.Root open={isOpen} onOpenChange={(open) => !open && onClose?.()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-canvas/80 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          className={`
            fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2
            bg-surface border border-border rounded-lg
            focus:outline-none
            ${contentClassName}
          `}
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <Dialog.Title className="text-base font-semibold text-foreground">{title}</Dialog.Title>
            <Dialog.Close asChild>
              <button
                type="button"
                className="p-1 rounded-md text-muted hover:text-foreground hover:bg-surface-raised focus-visible:ring-2 focus-visible:ring-primary"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </Dialog.Close>
          </div>
          <div className="px-4 py-4 text-sm text-muted">{children}</div>
          {actions && (
            <div className="flex justify-end gap-2 px-4 py-3 border-t border-border bg-surface-raised/50">
              {actions}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
