import React, { useCallback, useMemo, useState } from 'react';
import * as ToastPrimitive from '@radix-ui/react-toast';
import { X } from 'lucide-react';
import { ToastContext } from './toast-context';

let idSeq = 0;

/**
 * App-level toast provider. Mount once in the admin Layout shell.
 */
export default function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback((opts) => {
    const id = ++idSeq;
    const entry = {
      id,
      title: opts.title ?? '',
      description: opts.description ?? '',
      variant: opts.variant ?? 'default',
      duration: opts.duration ?? 4000,
    };
    setToasts((prev) => [...prev, entry]);
    return id;
  }, []);

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  const variantStyles = {
    default: 'border-border bg-surface-raised text-foreground',
    success: 'border-success/30 bg-surface-raised text-foreground',
    error: 'border-danger/40 bg-surface-raised text-foreground',
    warning: 'border-warning/30 bg-surface-raised text-foreground',
  };

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider swipeDirection="right" duration={4000}>
        {children}
        {toasts.map((t) => (
          <ToastPrimitive.Root
            key={t.id}
            duration={t.duration}
            open
            onOpenChange={(open) => {
              if (!open) dismiss(t.id);
            }}
            className={`
              pointer-events-auto relative flex w-[360px] max-w-[calc(100vw-2rem)] gap-3
              rounded-lg border px-3 py-2.5
              ${variantStyles[t.variant] ?? variantStyles.default}
            `}
          >
            <div className="min-w-0 flex-1">
              {t.title && (
                <ToastPrimitive.Title className="text-sm font-medium text-foreground">
                  {t.title}
                </ToastPrimitive.Title>
              )}
              {t.description && (
                <ToastPrimitive.Description className="mt-0.5 text-xs text-muted leading-relaxed">
                  {t.description}
                </ToastPrimitive.Description>
              )}
            </div>
            <ToastPrimitive.Close
              className="shrink-0 rounded-md p-1 text-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary"
              aria-label="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        ))}
        <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}
