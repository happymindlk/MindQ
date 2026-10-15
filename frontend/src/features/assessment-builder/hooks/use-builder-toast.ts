import { useToast } from '../../../components/ui/useToast';

export type ToastVariant = 'default' | 'success' | 'error' | 'warning';

export interface ToastOptions {
  title: string;
  description?: string;
  variant?: ToastVariant;
  duration?: number;
}

export interface BuilderToast {
  toast: (opts: ToastOptions) => number;
  dismiss: (id: number) => void;
}

/** Typed facade over the JS ToastProvider context. */
export function useBuilderToast(): BuilderToast {
  return useToast() as unknown as BuilderToast;
}
