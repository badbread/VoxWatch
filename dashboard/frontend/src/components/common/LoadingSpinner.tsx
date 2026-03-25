/**
 * LoadingSpinner — spinner and skeleton loader variants.
 *
 * Provides two components:
 * - `LoadingSpinner`: animated SVG spinner for button/inline loading states
 * - `SkeletonBlock`: gray placeholder block for content areas while loading
 * - `CardSkeleton`: full card-shaped skeleton for page-level loading
 */

import { cn } from '@/utils/cn';

// ---------------------------------------------------------------------------
// Spinner
// ---------------------------------------------------------------------------

export interface LoadingSpinnerProps {
  /** Tailwind size class (default "h-5 w-5"). */
  size?: string;
  /** Additional className overrides. */
  className?: string;
}

/**
 * Animated circular spinner.
 *
 * @example
 *   <LoadingSpinner size="h-4 w-4" />
 */
export function LoadingSpinner({
  size = 'h-5 w-5',
  className,
}: LoadingSpinnerProps) {
  return (
    <svg
      className={cn('animate-spin text-blue-500', size, className)}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Skeleton block
// ---------------------------------------------------------------------------

export interface SkeletonBlockProps {
  /** Additional className (use h-*, w-*, rounded-* to shape the block). */
  className?: string;
}

/**
 * Animated placeholder block for skeleton loading states.
 *
 * @example
 *   <SkeletonBlock className="h-4 w-3/4 rounded" />
 */
export function SkeletonBlock({ className }: SkeletonBlockProps) {
  return (
    <div
      className={cn(
        'animate-pulse rounded bg-gray-200 dark:bg-gray-700',
        className,
      )}
      aria-hidden="true"
    />
  );
}

// ---------------------------------------------------------------------------
// Card skeleton
// ---------------------------------------------------------------------------

/**
 * Full card-shaped skeleton used while a data card is loading.
 */
export function CardSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        'rounded-xl border border-gray-200 bg-white p-5 shadow-card dark:border-gray-700/50 dark:bg-gray-900',
        className,
      )}
    >
      <div className="mb-4 flex items-center justify-between">
        <SkeletonBlock className="h-4 w-32 rounded" />
        <SkeletonBlock className="h-4 w-16 rounded" />
      </div>
      <SkeletonBlock className="mb-2 h-3 w-full rounded" />
      <SkeletonBlock className="mb-2 h-3 w-5/6 rounded" />
      <SkeletonBlock className="h-3 w-4/6 rounded" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Full-page centered spinner
// ---------------------------------------------------------------------------

/**
 * Centered spinner for full-page or section loading states.
 */
export function PageSpinner() {
  return (
    <div className="flex h-48 items-center justify-center">
      <LoadingSpinner size="h-8 w-8" />
    </div>
  );
}
