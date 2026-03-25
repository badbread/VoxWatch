/**
 * Toast — single animated notification item.
 *
 * Renders with a slide-in animation and auto-dismisses after the configured
 * duration. The dismiss button allows manual early close.
 */

import { useEffect } from 'react';
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Info,
  X,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { useStore } from '@/store';
import type { Toast as ToastType } from '@/store/slices/toastSlice';

export interface ToastProps {
  toast: ToastType;
}

const icons = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const variantStyles = {
  success:
    'border-green-200 bg-white dark:border-green-800 dark:bg-gray-900',
  error:
    'border-red-200 bg-white dark:border-red-800 dark:bg-gray-900',
  warning:
    'border-yellow-200 bg-white dark:border-yellow-800 dark:bg-gray-900',
  info:
    'border-blue-200 bg-white dark:border-blue-800 dark:bg-gray-900',
};

const iconStyles = {
  success: 'text-green-500',
  error: 'text-red-500',
  warning: 'text-yellow-500',
  info: 'text-blue-500',
};

/**
 * Single toast notification with auto-dismiss support.
 *
 * Pulls the removeToast action from the store so it can dismiss itself.
 */
export function Toast({ toast }: ToastProps) {
  const removeToast = useStore((s) => s.removeToast);
  const Icon = icons[toast.variant];

  useEffect(() => {
    if (toast.duration <= 0) return;
    const timer = setTimeout(() => removeToast(toast.id), toast.duration);
    return () => clearTimeout(timer);
  }, [toast.id, toast.duration, removeToast]);

  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        'animate-slide-in-top flex w-full max-w-sm items-start gap-3',
        'rounded-xl border p-4 shadow-lg',
        variantStyles[toast.variant],
      )}
    >
      <Icon
        className={cn('mt-0.5 h-4 w-4 flex-shrink-0', iconStyles[toast.variant])}
        aria-hidden="true"
      />
      <p className="flex-1 text-sm text-gray-800 dark:text-gray-200">
        {toast.message}
      </p>
      <button
        onClick={() => removeToast(toast.id)}
        aria-label="Dismiss notification"
        className="flex-shrink-0 rounded-md p-0.5 text-gray-400 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:text-gray-500 dark:hover:text-gray-300"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
