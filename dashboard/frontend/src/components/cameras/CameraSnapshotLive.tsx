/**
 * CameraSnapshotLive — auto-refreshing camera snapshot image.
 *
 * Re-fetches a new snapshot URL every 10 seconds via useCameraSnapshotQuery
 * and displays it in a fixed-aspect-ratio container. Shows a skeleton
 * placeholder while loading and a graceful error state on failure.
 */

import { useState } from 'react';
import { Camera, RefreshCw } from 'lucide-react';
import { cn } from '@/utils/cn';
import { SkeletonBlock } from '@/components/common/LoadingSpinner';
import { useCameraSnapshotQuery } from '@/hooks/useCameras';
import { formatTime } from '@/utils/formatters';

export interface CameraSnapshotLiveProps {
  cameraName: string;
  /** Additional className for the outer container. */
  className?: string;
  /** Whether to fetch snapshots at all (default true). */
  enabled?: boolean;
}

/**
 * Live snapshot viewer that auto-refreshes every 10 seconds.
 */
export function CameraSnapshotLive({
  cameraName,
  className,
  enabled = true,
}: CameraSnapshotLiveProps) {
  const [imgError, setImgError] = useState(false);
  const { data, isLoading, refetch, isFetching } = useCameraSnapshotQuery(
    cameraName,
    enabled,
  );

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-xl bg-gray-900',
        'aspect-video',
        className,
      )}
    >
      {/* Loading skeleton */}
      {isLoading && (
        <SkeletonBlock className="absolute inset-0 h-full w-full rounded-none" />
      )}

      {/* Error state */}
      {(imgError || (!isLoading && !data)) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-gray-500">
          <Camera className="h-10 w-10 opacity-30" />
          <span className="text-xs">Snapshot unavailable</span>
          <button
            onClick={() => {
              setImgError(false);
              void refetch();
            }}
            className="flex items-center gap-1 rounded-lg bg-gray-800 px-2.5 py-1 text-xs text-gray-300 hover:bg-gray-700"
          >
            <RefreshCw className="h-3 w-3" />
            Retry
          </button>
        </div>
      )}

      {/* Snapshot image */}
      {data && !imgError && (
        <img
          src={data.url}
          alt={`Live snapshot from ${cameraName}`}
          className="h-full w-full object-cover"
          onError={() => setImgError(true)}
          loading="lazy"
        />
      )}

      {/* Timestamp overlay */}
      {data && !imgError && (
        <div className="absolute bottom-0 left-0 right-0 flex items-center justify-between bg-gradient-to-t from-black/60 px-3 py-2">
          <span className="text-xs font-medium text-white/90">
            {cameraName}
          </span>
          <div className="flex items-center gap-1.5">
            {isFetching && (
              <RefreshCw className="h-3 w-3 animate-spin text-white/70" />
            )}
            <span className="font-mono text-xs text-white/70">
              {formatTime(data.timestamp)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
