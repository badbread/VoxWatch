/**
 * Display formatting utilities for the VoxWatch Dashboard.
 *
 * All functions are pure (no side-effects) so they are trivially testable and
 * safe to call inside React render functions without memoization concerns.
 */

// ---------------------------------------------------------------------------
// Time formatters
// ---------------------------------------------------------------------------

/**
 * Formats an ISO 8601 timestamp as a human-readable relative time string.
 *
 * Examples: "just now", "2 min ago", "3 hrs ago", "yesterday", "Mar 15"
 *
 * @param isoString - ISO 8601 date string (e.g. "2025-03-21T14:30:00Z")
 * @returns Human-readable relative time string
 */
export function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 10) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;

  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} min ago`;

  const diffHrs = Math.floor(diffMin / 60);
  if (diffHrs < 24) return `${diffHrs} hr${diffHrs !== 1 ? 's' : ''} ago`;

  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays === 1) return 'yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;

  // Fall back to absolute date for older events
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/**
 * Formats an ISO 8601 timestamp as an absolute date+time string.
 *
 * Example: "Mar 21, 2025 at 2:30 PM"
 *
 * @param isoString - ISO 8601 date string
 * @param includeSeconds - Whether to include seconds in the time portion
 */
export function formatDate(
  isoString: string,
  includeSeconds = false,
): string {
  const date = new Date(isoString);
  const datePart = date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
  const timePart = date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    ...(includeSeconds ? { second: '2-digit' } : {}),
    hour12: true,
  });
  return `${datePart} at ${timePart}`;
}

/**
 * Formats an ISO 8601 timestamp as a short time string for compact displays.
 *
 * Example: "2:30:05 PM"
 *
 * @param isoString - ISO 8601 date string
 */
export function formatTime(isoString: string): string {
  return new Date(isoString).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
}

/**
 * Formats a duration in milliseconds as a human-readable string.
 *
 * Examples: "450ms", "1.2s", "3m 45s"
 *
 * @param ms - Duration in milliseconds
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const min = Math.floor(sec / 60);
  const remSec = Math.floor(sec % 60);
  return `${min}m ${remSec}s`;
}

/**
 * Formats seconds as a readable uptime string.
 *
 * Example: "2d 3h 15m"
 *
 * @param totalSeconds - Total uptime in seconds
 */
export function formatUptime(totalSeconds: number): string {
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);

  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

// ---------------------------------------------------------------------------
// Score formatters
// ---------------------------------------------------------------------------

/**
 * Formats a raw detection confidence score (0.0–1.0) as a percentage string.
 *
 * Example: 0.875 → "87.5%"
 *
 * @param score - Float between 0.0 and 1.0
 * @param decimals - Number of decimal places (default 1)
 */
export function formatScore(score: number, decimals = 1): string {
  return `${(score * 100).toFixed(decimals)}%`;
}

/**
 * Returns a Tailwind color class for a detection confidence score.
 *
 * - >= 0.9 → green (high confidence)
 * - >= 0.7 → yellow/amber (medium confidence)
 * - < 0.7  → red (low confidence, below typical trigger threshold)
 *
 * @param score - Float between 0.0 and 1.0
 */
export function scoreColorClass(score: number): string {
  if (score >= 0.9) return 'text-green-600 dark:text-green-400';
  if (score >= 0.7) return 'text-amber-600 dark:text-amber-400';
  return 'text-red-600 dark:text-red-400';
}

/**
 * Returns badge background/text color classes for a score value.
 *
 * @param score - Float between 0.0 and 1.0
 */
export function scoreBadgeClass(score: number): string {
  if (score >= 0.9)
    return 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300';
  if (score >= 0.7)
    return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
  return 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300';
}

// ---------------------------------------------------------------------------
// Schedule formatters
// ---------------------------------------------------------------------------

/**
 * The subset of the active_hours config object that this formatter needs.
 *
 * Defined as a narrow interface so it can accept both the full Pydantic-typed
 * config object and a plain partial dict without a cast.
 */
export interface ActiveHoursShape {
  mode?: string;
  start?: string;
  end?: string;
}

/**
 * Returns a human-readable label for the VoxWatch active-hours schedule.
 *
 * Handles all three scheduling modes:
 *   - ``always``          → "Always active"
 *   - ``sunset_sunrise``  → "Sunset to sunrise"
 *   - ``fixed``           → "<start> - <end>" (e.g. "22:00 - 06:00")
 *
 * Falls back to "Always active" when ``activeHours`` is undefined or its
 * ``mode`` is unrecognised, so the UI never shows an empty string.
 *
 * This function was extracted from duplicate inline logic that existed in
 * both DashboardPage and CameraStatusCard.  Both components now call this
 * single source of truth.
 *
 * @param activeHours - Active hours config slice (may be undefined/null).
 * @returns Human-readable schedule label string.
 *
 * @example
 *   formatScheduleLabel({ mode: 'fixed', start: '22:00', end: '06:00' })
 *   // → "22:00 - 06:00"
 *
 *   formatScheduleLabel({ mode: 'sunset_sunrise' })
 *   // → "Sunset to sunrise"
 *
 *   formatScheduleLabel(undefined)
 *   // → "Always active"
 */
export function formatScheduleLabel(
  activeHours: ActiveHoursShape | undefined | null,
): string {
  if (!activeHours) return 'Always active';
  if (activeHours.mode === 'sunset_sunrise') return 'Sunset to sunrise';
  if (activeHours.mode === 'fixed') {
    const start = activeHours.start ?? '22:00';
    const end = activeHours.end ?? '06:00';
    return `${start} - ${end}`;
  }
  return 'Always active';
}


// ---------------------------------------------------------------------------
// Misc formatters
// ---------------------------------------------------------------------------

/**
 * Converts a snake_case or kebab-case identifier to Title Case.
 *
 * Example: "my_camera_name" → "My Camera Name"
 *
 * @param str - The identifier string to humanize
 */
export function humanize(str: string): string {
  return str
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Truncates a string to a maximum length, appending an ellipsis if needed.
 *
 * @param str - Source string
 * @param maxLen - Maximum characters before truncation (default 120)
 */
export function truncate(str: string, maxLen = 120): string {
  if (str.length <= maxLen) return str;
  return `${str.slice(0, maxLen - 1)}…`;
}

/**
 * Formats a number with thousands separators for display.
 *
 * Example: 1234567 → "1,234,567"
 *
 * @param n - The number to format
 */
export function formatNumber(n: number): string {
  return new Intl.NumberFormat('en-US').format(n);
}
