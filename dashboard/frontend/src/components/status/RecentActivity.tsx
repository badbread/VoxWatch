/**
 * RecentActivity — stacked list of recent camera detection events.
 *
 * Derives events from `last_detection_at` timestamps returned by the
 * `useServiceStatus` hook — no new API calls. Events are sorted newest-first
 * and capped at 5 items. When no events are available a neutral empty state
 * message is shown instead.
 *
 * Design rules applied:
 *  - Dark card surface, subtle row separators
 *  - Relative time display ("12s ago", "4m ago")
 *  - Green accent pulse dot for very recent events (<60 s)
 *  - Smooth transition-all on mount
 */

import { Clock, Radio } from 'lucide-react';
import { cn } from '@/utils/cn';
import { useServiceStatus } from '@/hooks/useServiceStatus';
import type { CameraStatus } from '@/types/status';

/** Maximum number of recent activity rows to display. */
const MAX_EVENTS = 5;

/**
 * Converts an ISO timestamp string into a human-readable relative string such
 * as "12s ago", "4m ago", or "2h ago". Returns null when the timestamp is
 * absent or unparseable.
 */
function relativeTime(iso: string | undefined): string | null {
  if (!iso) return null;
  const delta = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (delta < 0) return 'just now';
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

/** Returns true for events that happened within the last 60 seconds. */
function isRecent(iso: string | undefined): boolean {
  if (!iso) return false;
  return Date.now() - new Date(iso).getTime() < 60_000;
}

interface ActivityEvent {
  cameraName: string;
  detectedAt: string;
}

/**
 * Collects cameras that have a `last_detection_at` timestamp, sorts them
 * newest-first, and returns up to MAX_EVENTS items.
 */
function buildEvents(cameras: CameraStatus[]): ActivityEvent[] {
  return cameras
    .filter((c) => !!c.last_detection_at)
    .sort(
      (a, b) =>
        new Date(b.last_detection_at!).getTime() -
        new Date(a.last_detection_at!).getTime(),
    )
    .slice(0, MAX_EVENTS)
    .map((c) => ({ cameraName: c.name, detectedAt: c.last_detection_at! }));
}

/**
 * Dismissible recent-activity list derived from live status data.
 *
 * Renders inside the Dashboard page below the camera grid. The component has
 * no internal state — it re-renders whenever the status poll updates.
 */
export function RecentActivity() {
  const { status, isLoading } = useServiceStatus();

  const events = buildEvents(status?.cameras ?? []);

  return (
    <div className="rounded-2xl bg-white dark:bg-gray-900/80 border border-gray-200 dark:border-gray-800/60 p-5 space-y-3 transition-all duration-200">
      {/* Section header */}
      <div className="flex items-center gap-2">
        <Radio className="h-4 w-4 text-gray-500 dark:text-gray-400" aria-hidden="true" />
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 dark:text-gray-400">
          Recent Activity
        </h3>
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded-xl bg-gray-100 dark:bg-gray-800/50"
            />
          ))}
        </div>
      )}

      {!isLoading && events.length === 0 && (
        <p className="py-4 text-center text-sm text-gray-400 dark:text-gray-600">
          No recent activity — system monitoring.
        </p>
      )}

      {!isLoading && events.length > 0 && (
        <ul className="space-y-0">
          {events.map((event, idx) => {
            const rel = relativeTime(event.detectedAt);
            const recent = isRecent(event.detectedAt);

            return (
              <li
                key={`${event.cameraName}-${event.detectedAt}`}
                className={cn(
                  'flex items-start gap-3 px-1 py-3 transition-all duration-200',
                  idx < events.length - 1 &&
                    'border-b border-gray-100 dark:border-gray-800/50',
                )}
              >
                {/* Pulse dot — green for recent, gray for older */}
                <span className="mt-1.5 flex h-2.5 w-2.5 flex-shrink-0 items-center justify-center">
                  {recent ? (
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-60" />
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" />
                    </span>
                  ) : (
                    <span className="h-2 w-2 rounded-full bg-gray-300 dark:bg-gray-600" />
                  )}
                </span>

                {/* Event details */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">
                      Person detected —{' '}
                      <span className="text-green-400">{event.cameraName}</span>
                    </span>
                    <span className="flex-shrink-0 flex items-center gap-1 text-xs text-gray-400 dark:text-gray-500">
                      <Clock className="h-3 w-3" aria-hidden="true" />
                      {rel}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                    Audio deterrent dispatched · VoxWatch active
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
