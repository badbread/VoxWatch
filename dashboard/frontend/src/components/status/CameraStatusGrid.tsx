/**
 * CameraStatusGrid — responsive grid of CameraStatusCard tiles.
 *
 * Reads camera status from the live service status in the store, which is
 * updated by WebSocket messages and the polling fallback.
 */

import { Camera } from 'lucide-react';
import { cn } from '@/utils/cn';
import { CameraStatusCard } from './CameraStatusCard';
import { EmptyState } from '@/components/common/EmptyState';
import { CardSkeleton } from '@/components/common/LoadingSpinner';
import { useServiceStatus } from '@/hooks/useServiceStatus';
import type { CameraStatus } from '@/types/status';

export interface CameraStatusGridProps {
  onCameraClick?: (camera: CameraStatus) => void;
  selectedName?: string | undefined;
}

/**
 * Grid of all configured camera status tiles.
 */
export function CameraStatusGrid({ onCameraClick, selectedName }: CameraStatusGridProps = {}) {
  const { status, isLoading } = useServiceStatus();

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    );
  }

  // Only show cameras that are actively monitored by VoxWatch (enabled===true).
  // The status API merges Frigate-only and go2rtc-only cameras in with enabled=false
  // so they appear on the Audio / Cameras pages without cluttering the dashboard.
  const cameras = (status?.cameras ?? []).filter((c) => c.enabled);

  if (cameras.length === 0) {
    return (
      <EmptyState
        icon={<Camera className="h-8 w-8 text-gray-400" />}
        title="No cameras configured"
        description="Go to the Cameras page to add cameras to VoxWatch."
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {cameras.map((camera) => (
        <button
          key={camera.name}
          type="button"
          onClick={() => onCameraClick?.(camera)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onCameraClick?.(camera);
            }
          }}
          aria-pressed={selectedName === camera.name}
          aria-label={`Select camera ${camera.name}`}
          className={cn(
            'w-full cursor-pointer rounded-2xl text-left transition-all duration-200',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-green-500/60',
            onCameraClick && 'hover:ring-1 hover:ring-green-500/30',
            selectedName === camera.name && 'ring-2 ring-green-500/60',
          )}
        >
          <CameraStatusCard camera={camera} />
        </button>
      ))}
    </div>
  );
}
