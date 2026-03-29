/**
 * CameraStatusCard — dashboard camera tile for the monitoring grid.
 *
 * Visual redesign applied:
 *  - Dark card surface with subtle shadow and rounded-2xl corners.
 *  - Camera name + green/gray online dot instead of text badge.
 *  - Placeholder preview area (dark box) in the middle of the card — ready for
 *    a future live thumbnail when snapshot streaming is available.
 *  - VoxWatch state rendered as a small color-coded badge at the bottom.
 *  - Hover: lift + green shadow glow to reinforce "clickable" affordance.
 *  - No-speaker cards get a red tint and reduced opacity.
 *
 * Clicking still navigates to the Cameras page via the parent grid wrapper.
 */

import { Camera } from 'lucide-react';
import { cn } from '@/utils/cn';
import { useConfigQuery } from '@/hooks/useConfig';
import { formatScheduleLabel } from '@/utils/formatters';
import type { CameraStatus } from '@/types/status';

export interface CameraStatusCardProps {
  camera: CameraStatus;
}

/**
 * Returns true when the camera has been positively identified as having no
 * audio output at all and therefore cannot work with VoxWatch.
 *
 * We only return true when speaker_status is explicitly "none" — cameras that
 * have not been identified yet get the benefit of the doubt.
 */
function isSpeakerIncompatible(camera: CameraStatus): boolean {
  return camera.speaker_status === 'none';
}

/** Derive the badge label and color class from camera state. */
function stateLabel(
  enabled: boolean,
  noSpeaker: boolean,
  frigateOnline: boolean | undefined,
): { text: string; color: string } {
  if (noSpeaker) return { text: 'Incompatible', color: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400' };
  if (enabled && frigateOnline !== false) return { text: 'VoxWatch On', color: 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-400' };
  if (enabled && frigateOnline === false) return { text: 'Camera Offline', color: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400' };
  if (frigateOnline === false) return { text: 'Offline', color: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500' };
  return { text: 'Disabled', color: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500' };
}

/**
 * Individual camera tile for the dashboard monitoring grid.
 */
export function CameraStatusCard({ camera }: CameraStatusCardProps) {
  const { data: config } = useConfigQuery();
  const noSpeaker = isSpeakerIncompatible(camera);

  const isOnline = camera.frigate_online !== false;
  const isActive = camera.enabled && !noSpeaker && isOnline;

  const { text: badgeText, color: badgeColor } = stateLabel(
    camera.enabled,
    noSpeaker,
    camera.frigate_online,
  );

  // Per-camera schedule takes priority over global active_hours.
  const cameraSchedule = config?.cameras?.[camera.name]?.schedule;
  const scheduleLabel = cameraSchedule
    ? cameraSchedule.mode === 'always'
      ? '24/7'
      : cameraSchedule.mode === 'scheduled'
        ? `${cameraSchedule.start ?? '22:00'} - ${cameraSchedule.end ?? '06:00'}`
        : cameraSchedule.mode === 'sunset_sunrise'
          ? 'Sunset - Sunrise'
          : formatScheduleLabel(config?.conditions?.active_hours)
    : formatScheduleLabel(config?.conditions?.active_hours);

  return (
    <div
      className={cn(
        'group relative flex flex-col rounded-2xl border bg-white dark:bg-gray-900/70 transition-all duration-200',
        'hover:shadow-lg hover:shadow-green-500/5 dark:hover:shadow-green-500/10 hover:-translate-y-0.5',
        isActive
          ? 'border-gray-200 dark:border-gray-700/60'
          : 'border-gray-200 dark:border-gray-800/60 opacity-60',
      )}
    >
      {/* Header row — camera name + status dot */}
      <div className="flex items-center justify-between gap-2 px-3.5 pt-3.5">
        <div className="flex items-center gap-2 min-w-0">
          <Camera className="h-3.5 w-3.5 flex-shrink-0 text-gray-400 dark:text-gray-500" aria-hidden="true" />
          <span className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
            {camera.name}
          </span>
        </div>

        {/* Online indicator dot */}
        <span
          className={cn(
            'h-2.5 w-2.5 flex-shrink-0 rounded-full',
            isOnline ? 'bg-green-500' : 'bg-gray-600',
          )}
          aria-label={isOnline ? 'Online' : 'Offline'}
          title={isOnline ? 'Online' : 'Offline'}
        />
      </div>

      {/* Preview placeholder — future: live thumbnail */}
      <div
        className={cn(
          'mx-3.5 my-3 flex h-20 items-center justify-center rounded-xl',
          'bg-gray-100 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700/30',
        )}
        aria-hidden="true"
      >
        <Camera className="h-6 w-6 text-gray-300 dark:text-gray-700" />
      </div>

      {/* Footer row — schedule + badge */}
      <div className="flex items-center justify-between gap-2 px-3.5 pb-3.5">
        {isActive && (
          <span className="truncate text-xs text-gray-500 dark:text-gray-500">
            {scheduleLabel}
          </span>
        )}
        {noSpeaker && (
          <span className="truncate text-xs text-red-500">
            {camera.compatibility_notes ?? 'No audio output'}
          </span>
        )}
        {!isActive && !noSpeaker && (
          <span className="text-xs text-gray-400 dark:text-gray-600" />
        )}

        {/* State badge */}
        <span
          className={cn(
            'flex-shrink-0 rounded-lg px-2 py-0.5 text-xs font-semibold',
            badgeColor,
          )}
        >
          {badgeText}
        </span>
      </div>
    </div>
  );
}
