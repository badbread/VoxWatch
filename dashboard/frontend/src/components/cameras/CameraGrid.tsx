/**
 * CameraGrid — overview grid of all cameras with click-to-detail navigation.
 */

import { Camera } from 'lucide-react';
import { cn } from '@/utils/cn';
import { Badge } from '@/components/common/Badge';
import { CardSkeleton } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { useCamerasQuery } from '@/hooks/useCameras';
import type { CameraStatus } from '@/types/status';
import type { BadgeVariant } from '@/components/common/Badge';

export interface CameraGridProps {
  onSelect: (camera: CameraStatus) => void;
  /** Name of the currently selected camera (for highlight ring). */
  selectedName?: string | undefined;
}

/**
 * Derive a badge variant from the available camera data.
 */
function cameraVariant(camera: CameraStatus): { variant: BadgeVariant; label: string } {
  if (camera.enabled && camera.frigate_online) return { variant: 'connected', label: 'VoxWatch Enabled' };
  if (camera.enabled && camera.frigate_online === false) return { variant: 'error', label: 'VoxWatch - Offline' };
  if (camera.enabled) return { variant: 'connected', label: 'VoxWatch Enabled' };
  if (camera.frigate_online === true) return { variant: 'neutral', label: 'Online' };
  if (camera.frigate_online === false) return { variant: 'error', label: 'Offline' };
  return { variant: 'neutral', label: 'Not Configured' };
}

/**
 * Clickable grid of all configured cameras.
 */
export function CameraGrid({ onSelect, selectedName }: CameraGridProps) {
  const { data: cameras, isLoading } = useCamerasQuery();

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[...Array(3)].map((_, i) => <CardSkeleton key={i} />)}
      </div>
    );
  }

  if (!cameras?.length) {
    return (
      <EmptyState
        icon={<Camera className="h-8 w-8 text-gray-400" />}
        title="No cameras configured"
        description="Add cameras in the Configuration page."
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {cameras.map((camera) => {
        const { variant, label } = cameraVariant(camera);
        const isSelected = camera.name === selectedName;
        return (
          <button
            key={camera.name}
            onClick={() => onSelect(camera)}
            className={cn(
              'group rounded-xl border bg-white p-4 text-left shadow-card transition-all',
              'hover:border-blue-200 hover:shadow-card-hover dark:bg-gray-900',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
              isSelected
                ? 'border-blue-500 ring-1 ring-blue-500 dark:border-blue-400'
                : 'border-gray-200 dark:border-gray-700/50 dark:hover:border-blue-800',
              !camera.enabled && 'opacity-60',
            )}
            aria-label={`View ${camera.name} camera details`}
          >
            <div className="mb-3 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <Camera className="h-4 w-4 flex-shrink-0 text-gray-400 group-hover:text-blue-500 transition-colors" />
                <span className="truncate font-semibold text-gray-900 dark:text-gray-100">
                  {camera.name}
                </span>
              </div>
              <Badge
                variant={variant}
                label={label}
                size="xs"
                dot={camera.enabled}
                className="flex-shrink-0 capitalize"
              />
            </div>
            {camera.fps != null && (
              <p className="text-xs text-gray-500 dark:text-gray-400">
                <span className="font-mono text-gray-700 dark:text-gray-300">
                  {camera.fps.toFixed(1)}
                </span>{' '}
                fps
              </p>
            )}
            <div className="mt-3 text-xs font-medium text-blue-600 opacity-0 transition-opacity group-hover:opacity-100 dark:text-blue-400">
              View details →
            </div>
          </button>
        );
      })}
    </div>
  );
}
