/**
 * CamerasPage — split layout with camera list on the left and detail panel on the right.
 *
 * Selecting a camera shows its detail (VoxWatch config, snapshot, stats)
 * in a static right panel without leaving the page.
 */

import { useState } from 'react';
import { CameraGrid } from '@/components/cameras/CameraGrid';
import { CameraDetail } from '@/components/cameras/CameraDetail';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import type { CameraStatus } from '@/types/status';

/**
 * Camera management page with side-by-side list + detail layout.
 */
export function CamerasPage() {
  const [selected, setSelected] = useState<CameraStatus | null>(null);

  return (
    <ErrorBoundary>
      <div className="flex gap-6 h-full">
        {/* Left: camera grid (always visible) */}
        <div className={selected ? 'w-1/3 min-w-[280px] flex-shrink-0' : 'w-full'}>
          <CameraGrid
            onSelect={setSelected}
            selectedName={selected?.name}
          />
        </div>

        {/* Right: detail panel (shown when a camera is selected) */}
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
