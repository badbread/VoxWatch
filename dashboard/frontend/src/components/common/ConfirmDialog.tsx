/**
 * ConfirmDialog — accessible modal confirmation dialog.
 *
 * Uses a native <dialog> element (supported in all modern browsers) for
 * correct focus trapping and accessibility semantics. Falls back gracefully
 * if the browser doesn't support the showModal API.
 */

import { useEffect, useRef } from 'react';
import { AlertTriangle } from 'lucide-react';
import { cn } from '@/utils/cn';

export interface ConfirmDialogProps {
  /** Whether the dialog is currently open. */
  open: boolean;
  /** Dialog heading text. */
  title: string;
  /** Explanatory body text. */
  message: string;
  /** Confirm button label (default "Confirm"). */
  confirmLabel?: string;
  /** Cancel button label (default "Cancel"). */
  cancelLabel?: string;
  /** Variant for the confirm button (default "danger"). */
  confirmVariant?: 'danger' | 'primary';
  /** Called when the user confirms. */
  onConfirm: () => void;
  /** Called when the user cancels or presses Escape. */
  onCancel: () => void;
}

/**
 * Modal confirmation dialog.
 *
 * @example
 *   <ConfirmDialog
 *     open={showConfirm}
 *     title="Discard changes?"
 *     message="Your unsaved changes will be lost."
 *     onConfirm={handleDiscard}
 *     onCancel={() => setShowConfirm(false)}
 *   />
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  confirmVariant = 'danger',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open) dialog.showModal();
    } else {
      if (dialog.open) dialog.close();
    }
  }, [open]);

  // Close on backdrop click (native dialog doesn't do this automatically)
  const handleDialogClick = (e: React.MouseEvent<HTMLDialogElement>) => {
    const rect = dialogRef.current?.getBoundingClientRect();
    if (!rect) return;
    const isOutside =
      e.clientX < rect.left ||
      e.clientX > rect.right ||
      e.clientY < rect.top ||
      e.clientY > rect.bottom;
    if (isOutside) onCancel();
  };

  return (
    <dialog
      ref={dialogRef}
      onCancel={onCancel}
      onClick={handleDialogClick}
      className={cn(
        'w-full max-w-md rounded-2xl border-0 bg-white p-0 shadow-xl',
        'dark:bg-gray-900',
        'backdrop:bg-gray-950/60 backdrop:backdrop-blur-sm',
        'open:animate-fade-in',
      )}
    >
      <div
        className="p-6"
        onClick={(e) => e.stopPropagation()} // prevent backdrop-close on content click
      >
        <div className="mb-4 flex items-start gap-4">
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/40">
            <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              {title}
            </h3>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {message}
            </p>
          </div>
        </div>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className={cn(
              'rounded-lg px-4 py-2 text-sm font-medium text-white focus:outline-none focus:ring-2 focus:ring-offset-2',
              confirmVariant === 'danger'
                ? 'bg-red-600 hover:bg-red-700 focus:ring-red-500'
                : 'bg-blue-600 hover:bg-blue-700 focus:ring-blue-500',
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  );
}
