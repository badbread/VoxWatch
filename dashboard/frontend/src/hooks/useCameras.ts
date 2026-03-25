/**
 * useCameras — React Query hook for the camera list and snapshot data.
 */

import { useQuery } from '@tanstack/react-query';
import { getCameras, getCameraSnapshot } from '@/api/cameras';

/** React Query key builders for camera queries. */
export const cameraKeys = {
  all: ['cameras'] as const,
  list: () => ['cameras', 'list'] as const,
  snapshot: (name: string) => ['cameras', 'snapshot', name] as const,
};

/**
 * Fetches the configured camera list with live status.
 *
 * Refreshes every 30 seconds as a polling fallback for cameras whose status
 * doesn't arrive via WebSocket.
 */
export function useCamerasQuery() {
  return useQuery({
    queryKey: cameraKeys.list(),
    queryFn: getCameras,
    staleTime: 20_000,
    refetchInterval: 30_000,
  });
}

/**
 * Fetches an auto-refreshing snapshot URL for a single camera.
 *
 * Re-fetches every 10 seconds so the CameraSnapshotLive component shows
 * a reasonably current frame without streaming.
 *
 * @param cameraName - Frigate camera name
 * @param enabled - Whether to fetch at all (default true)
 */
export function useCameraSnapshotQuery(
  cameraName: string,
  enabled = true,
) {
  return useQuery({
    queryKey: cameraKeys.snapshot(cameraName),
    queryFn: () => getCameraSnapshot(cameraName),
    enabled,
    staleTime: 8_000,
    refetchInterval: 10_000,
  });
}
