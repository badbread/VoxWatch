/**
 * CameraStatusCard — dashboard camera tile with color-coded metadata.
 *
 * Shows a "No speaker" error badge when a camera has been identified as having
 * no audio output, and suppresses the "VoxWatch Enabled" badge in that case
 * since the deterrent cannot function.
 */

import { Camera } from 'lucide-react';
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
      {/* Header */}
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

      {/* Compact one-liner — detailed stats are in the side panel */}
      {(camera.enabled || camera.fps != null) && !noSpeaker && (
        <div className="mt-2 flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          {camera.fps != null && (
            <span className="font-mono font-medium text-emerald-600 dark:text-emerald-400">
              {camera.fps.toFixed(1)} fps
            </span>
          )}
          {camera.enabled && camera.fps != null && (
            <span className="text-gray-300 dark:text-gray-600">·</span>
          )}
          {camera.enabled && (
            <span className="font-medium text-cyan-600 dark:text-cyan-400">{scheduleLabel}</span>
          )}
        </div>
      )}

      {/* Incompatibility note */}
      {noSpeaker && (
        <p className="mt-2 text-xs text-red-500 dark:text-red-400">
          {camera.compatibility_notes ?? 'No audio output — VoxWatch deterrent cannot function.'}
        </p>
      )}
    </div>
  );
}
