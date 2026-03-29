/**
 * ServiceStatusCard — full-width System Hero card for the Dashboard.
 *
 * Replaces the old list-based status card with a cinematic hero layout:
 *   LEFT — pulsing status dot, large "System Active/Degraded" headline,
 *           camera count subtext, and a stat row (Cameras · Audio · AI).
 *   RIGHT — most-recent detection event with relative timestamp and camera name.
 *
 * Data sources (no new API calls):
 *  - `useServiceStatus()` for Frigate/go2rtc reachability and camera list.
 *  - `useConfigQuery()` for AI provider model name displayed in the stat row.
 *
 * Color semantics: green = all services active, amber = partial degradation,
 * red = critical service(s) unreachable.
 */

import type { CSSProperties, ReactNode } from 'react';
import { Video, Server, Brain, Clock, Mic2, Theater } from 'lucide-react';
import { cn } from '@/utils/cn';
import { CardSkeleton } from '@/components/common/LoadingSpinner';
import { useServiceStatus } from '@/hooks/useServiceStatus';
import { useConfigQuery } from '@/hooks/useConfig';
import type { CameraStatus } from '@/types/status';

/**
 * Converts an ISO timestamp into a short relative-time string ("12s ago", "4m ago").
 * Returns null when the input is absent or unparseable.
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

/**
 * Returns the camera with the most recent last_detection_at timestamp, or null
 * when no cameras have ever fired.
 */
function mostRecentCamera(cameras: CameraStatus[]): CameraStatus | null {
  return cameras
    .filter((c) => !!c.last_detection_at)
    .sort(
      (a, b) =>
        new Date(b.last_detection_at!).getTime() -
        new Date(a.last_detection_at!).getTime(),
    )[0] ?? null;
}

/**
 * Full-width hero card displayed at the top of the Dashboard.
 *
 * Shows overall system health at a glance, optimised for a dark monitoring
 * environment where status must be readable without cognitive load.
 */
export function ServiceStatusCard() {
  const { status, isLoading } = useServiceStatus();
  const { data: config } = useConfigQuery();

  if (isLoading || !status) {
    return <CardSkeleton />;
  }

  const { frigate, go2rtc, cameras } = status;

  const allOk = frigate.reachable && go2rtc.reachable;
  const partialOk = frigate.reachable || go2rtc.reachable;

  // Headline state
  const headline = allOk ? 'System Active' : partialOk ? 'Partially Degraded' : 'Services Offline';
  const dotColor = allOk ? 'bg-green-500' : partialOk ? 'bg-amber-500' : 'bg-red-500';
  const pingColor = allOk ? 'bg-green-400' : partialOk ? 'bg-amber-400' : 'bg-red-400';
  const headlineColor = allOk
    ? 'text-green-400'
    : partialOk
      ? 'text-amber-400'
      : 'text-red-400';
  const glowStyle: CSSProperties = allOk
    ? { boxShadow: '0 0 32px rgba(34,197,94,0.08), 0 0 0 1px rgba(34,197,94,0.12)' }
    : partialOk
      ? { boxShadow: '0 0 32px rgba(245,158,11,0.08), 0 0 0 1px rgba(245,158,11,0.12)' }
      : { boxShadow: '0 0 32px rgba(239,68,68,0.08), 0 0 0 1px rgba(239,68,68,0.12)' };

  // Stats
  // enabledCameras: cameras with enabled===true — these are the actively monitored
  // VoxWatch cameras shown in the dashboard. Frigate-only / go2rtc-only cameras that
  // have not been enrolled in VoxWatch are merged by the backend with enabled=false
  // and are excluded from the count.
  const enabledCameras = cameras.filter((c) => c.enabled).length;
  const audioReady = go2rtc.reachable;
  const aiModel = config?.ai?.primary?.model ?? null;
  const aiConnected = frigate.reachable; // proxy for AI availability
  const ttsEngine = config?.tts?.engine ?? 'piper';
  const modeName = config?.response_mode?.name ?? config?.persona?.name ?? 'standard';

  // Last event
  const lastCamera = mostRecentCamera(cameras);
  const lastRel = relativeTime(lastCamera?.last_detection_at);

  return (
    <div
      className={cn(
        'rounded-2xl bg-gradient-to-r from-blue-50 via-white to-blue-50 dark:from-gray-900 dark:via-gray-800 dark:to-gray-900',
        'border border-gray-200 dark:border-gray-700/40 px-6 py-5 transition-all duration-200',
      )}
      style={glowStyle}
      aria-label="System status hero"
    >
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">

        {/* ── LEFT: headline + stats ────────────────────────────────────── */}
        <div className="space-y-3">
          {/* Status dot + headline */}
          <div className="flex items-center gap-3">
            <span className="relative flex h-3.5 w-3.5 flex-shrink-0">
              <span
                className={cn(
                  'absolute inline-flex h-full w-full animate-ping rounded-full opacity-60',
                  pingColor,
                )}
              />
              <span
                className={cn(
                  'relative inline-flex h-3.5 w-3.5 rounded-full',
                  dotColor,
                )}
              />
            </span>
            <h1 className={cn('text-xl font-bold tracking-tight', headlineColor)}>
              {headline}
            </h1>
          </div>

          {/* Subtext */}
          {enabledCameras > 0 ? (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Monitoring{' '}
              <span className="font-semibold text-gray-900 dark:text-gray-200">
                {enabledCameras}
              </span>{' '}
              camera{enabledCameras !== 1 ? 's' : ''}
            </p>
          ) : (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              No cameras configured —{' '}
              <a
                href="/cameras"
                className="font-medium text-blue-500 hover:text-blue-400 dark:text-blue-400 dark:hover:text-blue-300"
              >
                Set up cameras →
              </a>
            </p>
          )}

          {/* Stat pills row */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
            <StatPill
              icon={<Video className="h-3.5 w-3.5" aria-hidden="true" />}
              label="Cameras"
              value={String(enabledCameras)}
              ok={frigate.reachable}
            />
            <span className="text-gray-400 dark:text-gray-700" aria-hidden="true">·</span>
            <StatPill
              icon={<Server className="h-3.5 w-3.5" aria-hidden="true" />}
              label="Audio"
              value={audioReady ? 'Ready' : 'Unavailable'}
              ok={audioReady}
            />
            <span className="text-gray-400 dark:text-gray-700" aria-hidden="true">·</span>
            <StatPill
              icon={<Brain className="h-3.5 w-3.5" aria-hidden="true" />}
              label="AI"
              value={aiConnected ? (aiModel ?? 'Connected') : 'Disconnected'}
              ok={aiConnected}
            />
            <span className="text-gray-400 dark:text-gray-700" aria-hidden="true">·</span>
            <StatPill
              icon={<Mic2 className="h-3.5 w-3.5" aria-hidden="true" />}
              label="TTS"
              value={ttsEngine}
              ok
            />
            <span className="text-gray-400 dark:text-gray-700" aria-hidden="true">·</span>
            <StatPill
              icon={<Theater className="h-3.5 w-3.5" aria-hidden="true" />}
              label="Mode"
              value={modeName.replace(/_/g, ' ')}
              ok
            />
          </div>
        </div>

        {/* ── RIGHT: last event ─────────────────────────────────────────── */}
        <div
          className={cn(
            'flex-shrink-0 rounded-xl border border-gray-200 bg-gray-50 dark:border-gray-700/50 dark:bg-gray-800/50 px-4 py-3 sm:min-w-[200px]',
          )}
        >
          {lastCamera && lastRel ? (
            <>
              <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-widest text-gray-500 dark:text-gray-500">
                <Clock className="h-3 w-3" aria-hidden="true" />
                Last Event
              </p>
              <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                {lastRel}
              </p>
              <p className="mt-0.5 text-xs text-green-400 truncate">
                {lastCamera.name}
              </p>
            </>
          ) : (
            <>
              <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-widest text-gray-500 dark:text-gray-500">
                <Clock className="h-3 w-3" aria-hidden="true" />
                Last Event
              </p>
              <p className="text-sm text-gray-500 italic">No events yet</p>
            </>
          )}
        </div>

      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: StatPill
// ---------------------------------------------------------------------------

interface StatPillProps {
  icon: ReactNode;
  label: string;
  value: string;
  ok: boolean;
}

/**
 * Compact label + value pair for the hero stat row.
 * Green when the associated service is healthy, amber/gray when not.
 */
function StatPill({ icon, label, value, ok }: StatPillProps) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={ok ? 'text-gray-500 dark:text-gray-400' : 'text-gray-400 dark:text-gray-600'} aria-hidden="true">
        {icon}
      </span>
      <span className="text-gray-500 dark:text-gray-500">{label}:</span>
      <span className={cn('font-semibold', ok ? 'text-gray-800 dark:text-gray-200' : 'text-amber-500 dark:text-amber-400')}>
        {value}
      </span>
    </span>
  );
}
