/**
 * CameraStatusCard — dashboard camera tile for the monitoring grid.
 *
 * Displays: camera name, status badge, schedule, and last detection time.
 * Clicking navigates to the Cameras page (handled by CameraStatusGrid).
 *
 * Shows a "No speaker" error badge when a camera has been identified as having
 * no audio output, and suppresses the "VoxWatch Enabled" badge in that case
 * since the deterrent cannot function.
 */

import { Camera, Clock, Zap } from 'lucide-react';
import { cn } from '@/utils/cn';
import { Badge } from '@/components/common/Badge';
import { useConfigQuery } from '@/hooks/useConfig';
import { formatScheduleLabel } from '@/utils/formatters';
import type { CameraStatus } from '@/types/status';
import type { BadgeVariant } from '@/components/common/Badge';

export interface CameraStatusCardProps {
  camera: CameraStatus;
}

/**
 * Returns true when the camera has been positively identified as having no
 * audio output at all and therefore cannot work with VoxWatch.
 *
 * We only return true when the speaker_status is explicitly "none" — cameras
 * that have not been identified yet (speaker_status undefined or "unknown")
 * get the benefit of the doubt.
 */
function isSpeakerIncompatible(camera: CameraStatus): boolean {
  return camera.speaker_status === 'none';
}

export function CameraStatusCard({ camera }: CameraStatusCardProps) {
  const { data: config } = useConfigQuery();
  const noSpeaker = isSpeakerIncompatible(camera);

  let variant: BadgeVariant = 'info';
  let label = 'Online';

  if (noSpeaker) {
    // Camera is incompatible — show a neutral/disabled state even if "enabled"
    // was set before identification confirmed no audio output.
    variant = 'neutral';
    label = 'Incompatible';
  } else if (camera.enabled && camera.frigate_online !== false) {
    variant = 'connected';
    label = 'VoxWatch Enabled';
  } else if (camera.enabled && camera.frigate_online === false) {
    variant = 'error';
    label = 'VoxWatch - Offline';
  } else if (camera.frigate_online === false) {
    variant = 'neutral';
    label = 'Offline';
  }

  const scheduleLabel = formatScheduleLabel(config?.conditions?.active_hours);

  return (
    <div
      className={cn(
        'rounded-xl border bg-white p-4 dark:bg-gray-900',
        camera.enabled && !noSpeaker
          ? 'border-gray-200 dark:border-gray-700/50'
          : 'border-gray-100 opacity-60 dark:border-gray-800',
      )}
    >
      {/* Header row — camera name + status badge */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Camera className="h-4 w-4 flex-shrink-0 text-gray-400" aria-hidden="true" />
          <span className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
            {camera.name}
          </span>
        </div>
        <div className="flex flex-shrink-0 items-center gap-1.5">
          {/* "No speaker" badge — only shown when identification confirmed no audio output */}
          {noSpeaker && (
            <Badge variant="error" label="No speaker" size="xs" />
          )}
          <Badge
            variant={variant}
            label={label}
            size="xs"
            dot={camera.enabled && !noSpeaker}
            className="flex-shrink-0"
          />
        </div>
      </div>

      {/* Enabled camera metadata — schedule and last detection */}
      {camera.enabled && !noSpeaker && (
        <div className="mt-2 space-y-1">
          {/* Active schedule */}
          <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
            <Clock className="h-3 w-3 text-cyan-500 flex-shrink-0" aria-hidden="true" />
            <span className="font-medium text-cyan-600 dark:text-cyan-400">{scheduleLabel}</span>
          </div>

          {/* Last detection time */}
          {camera.last_detection_at ? (
            <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
              <Zap className="h-3 w-3 text-rose-500 flex-shrink-0" aria-hidden="true" />
              <span className="text-rose-600 dark:text-rose-400">
                {new Date(camera.last_detection_at).toLocaleString()}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500">
              <Zap className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
              <span>No detections yet</span>
            </div>
          )}
        </div>
      )}

      {/* Incompatibility note */}
      {noSpeaker && (
        <p className="mt-2 text-xs text-red-500 dark:text-red-400">
          {camera.compatibility_notes ?? 'No audio output — VoxWatch deterrent cannot function.'}
        </p>
      )}

      {/* Hover hint rendered by the parent button wrapper — nothing to add here */}
    </div>
  );
}
