/**
 * ToastContainer — fixed-position stack that renders all queued toasts.
 *
 * Positioned in the top-right corner on desktop and top-center on mobile.
 * Renders into a React portal so it always sits above other content.
 */

import { createPortal } from 'react-dom';
import { useStore } from '@/store';
import { Toast } from './Toast';

/**
 * Renders the full toast notification stack.
 *
 * Place this once inside App (outside the Router/layout tree) so toasts
 * appear over all pages and modals.
 */
export function ToastContainer() {
  const toasts = useStore((s) => s.toasts);

  if (toasts.length === 0) return null;

  return createPortal(
    <div
      aria-label="Notifications"
      className="pointer-events-none fixed right-4 top-4 z-50 flex flex-col items-end gap-2 sm:right-6 sm:top-6"
    >
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto w-full max-w-sm">
          <Toast toast={toast} />
        </div>
      ))}
    </div>,
    document.body,
  );
}
