/**
 * Badge — compact status label with semantic color variants.
 *
 * Used throughout the dashboard for connection health, detection scores,
 * stage outcomes, and other categorical indicators.
 */

import { cn } from '@/utils/cn';

/** Semantic badge variants. */
export type BadgeVariant =
  | 'connected'
  | 'disconnected'
  | 'warning'
  | 'error'
  | 'success'
  | 'info'
  | 'neutral'
  | 'detection';

/** Size options for the badge. */
export type BadgeSize = 'xs' | 'sm' | 'md';

export interface BadgeProps {
  /** Display text inside the badge. */
  label: string;
  /** Color variant. */
  variant?: BadgeVariant;
  /** Size variant (default "sm"). */
  size?: BadgeSize;
  /** Render a small pulsing dot before the label. */
  dot?: boolean;
  /** Additional className overrides. */
  className?: string;
}

const variantClasses: Record<BadgeVariant, string> = {
  connected:
    'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  disconnected:
    'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
  warning:
    'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300',
  error:
    'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
  success:
    'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  info:
    'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  neutral:
    'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  detection:
    'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
};

const dotColors: Record<BadgeVariant, string> = {
  connected: 'bg-green-500',
  disconnected: 'bg-gray-400',
  warning: 'bg-yellow-500',
  error: 'bg-red-500',
  success: 'bg-green-500',
  info: 'bg-blue-500',
  neutral: 'bg-gray-400',
  detection: 'bg-amber-500',
};

const sizeClasses: Record<BadgeSize, string> = {
  xs: 'px-1.5 py-0.5 text-xs',
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-sm',
};

/**
 * Compact status badge.
 *
 * @example
 *   <Badge variant="connected" label="Online" dot />
 *   <Badge variant="error" label="Offline" />
 */
export function Badge({
  label,
  variant = 'neutral',
  size = 'sm',
  dot = false,
  className,
}: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full font-medium',
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
    >
      {dot && (
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full',
            dotColors[variant],
            variant === 'connected' && 'animate-pulse-dot',
          )}
          aria-hidden="true"
        />
      )}
      {label}
    </span>
  );
}
