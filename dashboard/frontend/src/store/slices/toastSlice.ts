/**
 * Toast slice — Zustand state for the global notification queue.
 *
 * Toasts are queued here and rendered by ToastContainer. Each toast has an
 * auto-generated ID, a variant, and an optional duration before auto-dismiss.
 */

/** Visual severity of a toast notification. */
export type ToastVariant = 'success' | 'error' | 'warning' | 'info';

/** A single toast notification. */
export interface Toast {
  /** Auto-generated unique identifier. */
  id: string;
  /** The notification message text. */
  message: string;
  /** Visual variant controlling icon and color. */
  variant: ToastVariant;
  /** Auto-dismiss after this many milliseconds. 0 = no auto-dismiss. */
  duration: number;
  /** ISO 8601 timestamp when the toast was added. */
  createdAt: string;
}

/** Shape of the toast slice within the root store. */
export interface ToastSlice {
  toasts: Toast[];
  addToast: (
    message: string,
    variant?: ToastVariant,
    duration?: number,
  ) => string;
  removeToast: (id: string) => void;
  clearToasts: () => void;
}

/** Generates a short unique ID for toast items. */
function genId(): string {
  return `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

/** Zustand slice factory for toast state. */
export const createToastSlice = (
  set: (
    partial:
      | Partial<ToastSlice>
      | ((state: ToastSlice) => Partial<ToastSlice>),
  ) => void,
): ToastSlice => ({
  toasts: [],

  addToast: (
    message: string,
    variant: ToastVariant = 'info',
    duration = 4000,
  ): string => {
    const id = genId();
    const toast: Toast = {
      id,
      message,
      variant,
      duration,
      createdAt: new Date().toISOString(),
    };
    set((state) => ({ toasts: [...state.toasts, toast] }));
    return id;
  },

  removeToast: (id: string) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    })),

  clearToasts: () => set({ toasts: [] }),
});
