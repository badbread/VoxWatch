/**
 * useToast — convenience hook for dispatching toast notifications.
 *
 * Wraps the store's addToast action with pre-named variants so call sites
 * don't need to import the store directly.
 *
 * @example
 *   const toast = useToast();
 *   toast.success('Config saved!');
 *   toast.error('Something went wrong.');
 */

import { useStore } from '@/store';
import type { ToastVariant } from '@/store/slices/toastSlice';

export interface UseToastReturn {
  /** Show a success notification. */
  success: (message: string, duration?: number) => void;
  /** Show an error notification. */
  error: (message: string, duration?: number) => void;
  /** Show a warning notification. */
  warning: (message: string, duration?: number) => void;
  /** Show an informational notification. */
  info: (message: string, duration?: number) => void;
  /** Show a notification with an explicit variant. */
  show: (message: string, variant: ToastVariant, duration?: number) => void;
}

/**
 * Hook providing typed toast dispatch methods.
 */
export function useToast(): UseToastReturn {
  const addToast = useStore((s) => s.addToast);

  return {
    success: (message, duration) =>
      addToast(message, 'success', duration),
    error: (message, duration) =>
      addToast(message, 'error', duration ?? 6000),
    warning: (message, duration) =>
      addToast(message, 'warning', duration),
    info: (message, duration) =>
      addToast(message, 'info', duration),
    show: (message, variant, duration) =>
      addToast(message, variant, duration),
  };
}
