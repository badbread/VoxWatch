/**
 * ConfigSaveBar — sticky bottom bar with validation status, change review,
 * and save/discard actions for the configuration editor.
 *
 * Shows a green checkmark when config is valid, or a red error count when
 * validation failures exist. Includes a "Review Changes" button that opens
 * a slide-up panel showing a diff of all modifications.
 */

import { useState } from 'react';
import {
  CheckCircle,
  AlertCircle,
  Loader,
  Save,
  RotateCcw,
  FileText,
  X,
  Plus,
  Minus,
  Pencil,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import type { ConfigValidationError, VoxWatchConfig } from '@/types/config';

/** Single change entry for the diff panel. */
interface ConfigChange {
  path: string;
  type: 'added' | 'removed' | 'changed';
  oldValue?: string;
  newValue?: string;
}

export interface ConfigSaveBarProps {
  /** True when the form has unsaved changes. */
  isDirty: boolean;
  /** True while the save mutation is in flight. */
  isSaving: boolean;
  /** Validation errors from the client-side validator. */
  errors: ConfigValidationError[];
  /** The original (saved) config for diffing. */
  originalConfig: VoxWatchConfig | null;
  /** The current (edited) config for diffing. */
  currentConfig: VoxWatchConfig | null;
  /** Called when the user clicks Save. */
  onSave: () => void;
  /** Called when the user clicks Discard. */
  onDiscard: () => void;
}

/**
 * Recursively compare two objects and return a list of changes.
 */
function diffConfigs(
  original: Record<string, unknown>,
  current: Record<string, unknown>,
  prefix = '',
): ConfigChange[] {
  const changes: ConfigChange[] = [];
  const allKeys = new Set([...Object.keys(original), ...Object.keys(current)]);

  for (const key of allKeys) {
    const path = prefix ? `${prefix}.${key}` : key;
    const oldVal = original[key];
    const newVal = current[key];

    if (oldVal === undefined && newVal !== undefined) {
      changes.push({ path, type: 'added', newValue: formatVal(newVal) });
    } else if (oldVal !== undefined && newVal === undefined) {
      changes.push({ path, type: 'removed', oldValue: formatVal(oldVal) });
    } else if (
      typeof oldVal === 'object' &&
      oldVal !== null &&
      typeof newVal === 'object' &&
      newVal !== null &&
      !Array.isArray(oldVal) &&
      !Array.isArray(newVal)
    ) {
      changes.push(
        ...diffConfigs(
          oldVal as Record<string, unknown>,
          newVal as Record<string, unknown>,
          path,
        ),
      );
    } else if (JSON.stringify(oldVal) !== JSON.stringify(newVal)) {
      changes.push({
        path,
        type: 'changed',
        oldValue: formatVal(oldVal),
        newValue: formatVal(newVal),
      });
    }
  }

  return changes;
}

function formatVal(v: unknown): string {
  if (v === null || v === undefined) return '(empty)';
  if (typeof v === 'string') return v || '(empty)';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return String(v);
  return JSON.stringify(v, null, 2);
}

/**
 * Sticky save/discard bar with change review panel.
 */
export function ConfigSaveBar({
  isDirty,
  isSaving,
  errors,
  originalConfig,
  currentConfig,
  onSave,
  onDiscard,
}: ConfigSaveBarProps) {
  const [showChanges, setShowChanges] = useState(false);
  const hasErrors = errors.length > 0;

  const changes =
    originalConfig && currentConfig
      ? diffConfigs(
          originalConfig as unknown as Record<string, unknown>,
          currentConfig as unknown as Record<string, unknown>,
        )
      : [];

  return (
    <>
      {/* Change review panel — slides up above the save bar */}
      {showChanges && (
        <div
          className={cn(
            'fixed bottom-14 left-0 right-0 z-30 max-h-[50vh] overflow-y-auto',
            'border-t border-gray-200 bg-gray-50 shadow-2xl dark:border-gray-700 dark:bg-gray-900',
            'md:left-16 lg:left-64',
          )}
        >
          <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2 dark:border-gray-700">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-gray-500" />
              <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                Pending Changes ({changes.length})
              </span>
            </div>
            <button
              onClick={() => setShowChanges(false)}
              className="rounded-lg p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-600 dark:hover:bg-gray-700 dark:hover:text-gray-300"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {changes.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-gray-500">
              No changes detected.
            </div>
          ) : (
            <div className="divide-y divide-gray-200 dark:divide-gray-700/50">
              {changes.map((change) => (
                <div
                  key={change.path}
                  className="flex items-start gap-3 px-4 py-2.5"
                >
                  {/* Change type icon */}
                  {change.type === 'added' && (
                    <Plus className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-green-500" />
                  )}
                  {change.type === 'removed' && (
                    <Minus className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-red-500" />
                  )}
                  {change.type === 'changed' && (
                    <Pencil className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-yellow-500" />
                  )}

                  <div className="min-w-0 flex-1">
                    <span className="font-mono text-xs font-semibold text-gray-700 dark:text-gray-300">
                      {change.path}
                    </span>

                    {change.type === 'changed' && (
                      <div className="mt-1 space-y-0.5">
                        <div className="flex items-start gap-1.5">
                          <span className="mt-px text-xs font-medium text-red-500">-</span>
                          <span className="break-all font-mono text-xs text-red-600 dark:text-red-400">
                            {change.oldValue}
                          </span>
                        </div>
                        <div className="flex items-start gap-1.5">
                          <span className="mt-px text-xs font-medium text-green-500">+</span>
                          <span className="break-all font-mono text-xs text-green-600 dark:text-green-400">
                            {change.newValue}
                          </span>
                        </div>
                      </div>
                    )}

                    {change.type === 'added' && (
                      <p className="mt-0.5 break-all font-mono text-xs text-green-600 dark:text-green-400">
                        {change.newValue}
                      </p>
                    )}

                    {change.type === 'removed' && (
                      <p className="mt-0.5 break-all font-mono text-xs text-red-600 dark:text-red-400">
                        {change.oldValue}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Save bar */}
      <div
        className={cn(
          'fixed bottom-0 left-0 right-0 z-30 transition-transform duration-200 ease-out',
          isDirty ? 'translate-y-0' : 'translate-y-full',
          'md:left-16 lg:left-64',
        )}
        aria-live="polite"
        aria-label="Configuration save bar"
      >
        <div className="flex items-center justify-between gap-4 border-t border-gray-200 bg-white px-4 py-3 shadow-lg dark:border-gray-700/50 dark:bg-gray-900 sm:px-6">
          {/* Validation status */}
          <div className="flex items-center gap-2">
            {isSaving ? (
              <Loader className="h-4 w-4 animate-spin text-blue-500" />
            ) : hasErrors ? (
              <AlertCircle className="h-4 w-4 text-red-500" />
            ) : (
              <CheckCircle className="h-4 w-4 text-green-500" />
            )}
            <span
              className={cn(
                'text-sm font-medium',
                isSaving
                  ? 'text-blue-600 dark:text-blue-400'
                  : hasErrors
                    ? 'text-red-600 dark:text-red-400'
                    : 'text-green-700 dark:text-green-400',
              )}
            >
              {isSaving
                ? 'Saving...'
                : hasErrors
                  ? `${errors.length} validation error${errors.length !== 1 ? 's' : ''}`
                  : `Ready to save (${changes.length} change${changes.length !== 1 ? 's' : ''})`}
            </span>
          </div>

          {/* Actions */}
          <div className="flex flex-shrink-0 items-center gap-2">
            {/* Review Changes button */}
            <button
              onClick={() => setShowChanges(!showChanges)}
              className={cn(
                'flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors',
                showChanges
                  ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-700 dark:bg-blue-950/30 dark:text-blue-300'
                  : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700',
              )}
            >
              <FileText className="h-3.5 w-3.5" />
              {changes.length} Change{changes.length !== 1 ? 's' : ''}
            </button>

            <button
              onClick={onDiscard}
              disabled={isSaving}
              className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Discard
            </button>
            <button
              onClick={onSave}
              disabled={isSaving || hasErrors}
              className={cn(
                'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-white',
                'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
                'disabled:cursor-not-allowed disabled:opacity-50',
                hasErrors ? 'bg-gray-400' : 'bg-blue-600 hover:bg-blue-700',
              )}
            >
              {isSaving ? (
                <Loader className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              Save Configuration
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
