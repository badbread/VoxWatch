/**
 * CamerasPage — unified camera management hub.
 *
 * Shows all cameras (VoxWatch-enabled and discovered/unconfigured) in a grid
 * on the left.  Selecting a camera opens a full detail panel on the right that
 * includes: live snapshot, ONVIF identification, compatibility status,
 * two-way audio info, and inline VoxWatch configuration (add / edit / remove).
 *
 * Deep-linking: navigating to /cameras?selected={name} automatically opens
 * the detail panel for the named camera.  The Dashboard uses this to hand
 * off camera clicks without leaving context.
 *
 * Mobile: when a camera is selected the grid is hidden and the detail panel
 * expands to full width.
 */

import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CameraGrid } from '@/components/cameras/CameraGrid';
import { CameraDetail } from '@/components/cameras/CameraDetail';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { useCamerasQuery } from '@/hooks/useCameras';
import type { CameraStatus } from '@/types/status';

/**
 * Camera management page — split list / detail layout with deep-link support.
 */
export function CamerasPage() {
  const [selected, setSelected] = useState<CameraStatus | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: cameras } = useCamerasQuery();

  /**
   * When the camera list loads (or reloads after a config save), check whether
   * the ?selected= query param refers to a known camera and auto-open it.
   * This handles both the initial deep-link from the Dashboard and the case
   * where the page is already mounted when a new camera is added.
   */
  useEffect(() => {
    const requestedName = searchParams.get('selected');
    if (!requestedName || !cameras?.length) return;

    const match = cameras.find((c) => c.name === requestedName);
    if (match) {
      setSelected(match);
      // Clean up the query param so the URL stays tidy after selection
      setSearchParams({}, { replace: true });
    }
  }, [cameras, searchParams, setSearchParams]);

  /**
   * Sync the selected camera object when the cameras list refreshes so the
   * detail panel always reflects the latest status data (fps, detection time, etc.).
   */
  useEffect(() => {
    if (!selected || !cameras?.length) return;
    const refreshed = cameras.find((c) => c.name === selected.name);
    if (refreshed) setSelected(refreshed);
    // Only re-run when the cameras list reference changes, not selected itself
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameras]);

  return (
    <ErrorBoundary>
      <div className="flex gap-6 h-full">
        {/* Left: camera grid — hidden on mobile when detail panel is open */}
        <div
          className={
            selected
              ? 'hidden sm:block w-1/3 min-w-[280px] flex-shrink-0'
              : 'w-full'
          }
        >
          <CameraGrid
            onSelect={setSelected}
            selectedName={selected?.name}
          />
        </div>

        {/* Right: detail panel — full width on mobile, flex-1 on desktop */}
        {selected && (
          <div className="flex-1 min-w-0 overflow-y-auto">
            <CameraDetail
              camera={selected}
              onBack={() => setSelected(null)}
            />
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}
