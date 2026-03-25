/**
 * FormField — shared form primitives used across all config form sections.
 *
 * Exports:
 *   inputCls(hasError)  — Tailwind class string for styled <input>/<select> elements.
 *   Field               — Labelled form field wrapper with optional error and hint text.
 */

import React from 'react';
import { cn } from '@/utils/cn';

/**
 * Returns a consistent Tailwind class string for text inputs and selects.
 * Switches to red ring/border styles when the field has a validation error.
 */
export function inputCls(hasError: boolean): string {
  return cn(
    'w-full rounded-lg border px-3 py-2 text-sm',
    'focus:outline-none focus:ring-2 focus:ring-blue-500',
    'dark:bg-gray-800 dark:text-gray-100',
    hasError
      ? 'border-red-400 focus:border-red-400 focus:ring-red-400 dark:border-red-600'
      : 'border-gray-300 focus:border-blue-500 dark:border-gray-600',
  );
}

export interface FieldProps {
  /** Label text rendered above the input. */
  label: string;
  /** Validation error message. Suppresses hint when present. */
  error?: string | undefined;
  /** The form control(s) to render inside the field. */
  children: React.ReactNode;
  /** Additional Tailwind classes applied to the outer wrapper div. */
  className?: string | undefined;
  /** Helper text shown below the input when there is no error. */
  hint?: string | undefined;
}

/**
 * Wraps a form control with a label, optional hint, and optional error message.
 * Import this (and inputCls) into any config form component that needs labelled fields.
 */
export function Field({ label, error, children, className, hint }: FieldProps) {
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
        {label}
      </label>
      {children}
      {hint && !error && (
        <p className="text-xs text-gray-400 dark:text-gray-500">{hint}</p>
      )}
      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  );
}
