/**
 * Card — reusable surface container.
 *
 * Provides consistent padding, border, rounded corners, and shadow for both
 * light and dark mode. Accepts an optional title, subtitle, and action slot
 * in the header row.
 */

import { type ReactNode } from 'react';
import { cn } from '@/utils/cn';

export interface CardProps {
  /** Optional card title displayed in the header row. */
  title?: string | undefined;
  /** Optional subtitle displayed below the title. */
  subtitle?: string | undefined;
  /** Optional element rendered in the top-right header slot (e.g. a button). */
  action?: ReactNode | undefined;
  /** Card body content. */
  children: ReactNode;
  /** Additional className overrides for the root element. */
  className?: string | undefined;
  /** Additional className for the body padding wrapper. */
  bodyClassName?: string | undefined;
  /** Remove default padding from the card body (useful for tables/charts). */
  noPadding?: boolean | undefined;
}

/**
 * Surface card with an optional header row.
 *
 * @example
 *   <Card title="Detections" action={<Button>Refresh</Button>}>
 *     <p>Content here</p>
 *   </Card>
 */
export function Card({
  title,
  subtitle,
  action,
  children,
  className,
  bodyClassName,
  noPadding = false,
}: CardProps) {
  const hasHeader = title || subtitle || action;

  return (
    <div
      className={cn(
        'rounded-xl border border-gray-200 bg-white shadow-card',
        'dark:border-gray-700/50 dark:bg-gray-900',
        className,
      )}
    >
      {hasHeader && (
        <div className="flex items-start justify-between gap-4 px-5 pt-5">
          <div className="min-w-0 flex-1">
            {title && (
              <h3 className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
                {title}
              </h3>
            )}
            {subtitle && (
              <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                {subtitle}
              </p>
            )}
          </div>
          {action && <div className="flex-shrink-0">{action}</div>}
        </div>
      )}
      <div
        className={cn(
          !noPadding && 'p-5',
          hasHeader && !noPadding && 'pt-3',
          bodyClassName,
        )}
      >
        {children}
      </div>
    </div>
  );
}
