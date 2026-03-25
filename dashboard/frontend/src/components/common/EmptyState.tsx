/**
 * EmptyState — illustrated placeholder for empty data views.
 *
 * Shown when a list or table has no items to display, with an icon, title,
 * description, and optional call-to-action button.
 */

import { type ReactNode } from 'react';
import { cn } from '@/utils/cn';

export interface EmptyStateProps {
  /** Lucide (or any) icon element. */
  icon?: ReactNode;
  /** Short heading text. */
  title: string;
  /** Longer explanation. */
  description?: string;
  /** Optional call-to-action rendered below the description. */
  action?: ReactNode;
  /** Additional className for the root container. */
  className?: string;
}

/**
 * Illustrated empty state with icon, text, and optional action.
 *
 * @example
 *   <EmptyState
 *     icon={<AlertTriangle className="h-10 w-10 text-gray-400" />}
 *     title="No detections yet"
 *     description="Detections will appear here when VoxWatch processes events."
 *   />
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center py-12 text-center',
        className,
      )}
    >
      {icon && (
        <div className="mb-4 rounded-full bg-gray-100 p-4 dark:bg-gray-800">
          {icon}
        </div>
      )}
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        {title}
      </h3>
      {description && (
        <p className="mt-1 max-w-sm text-sm text-gray-500 dark:text-gray-400">
          {description}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
