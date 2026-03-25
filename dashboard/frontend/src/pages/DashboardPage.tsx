/**
 * DashboardPage — main landing page with service status overview and
 * a read-only camera monitoring grid.
 *
 * Camera management (add, edit, configure) now lives entirely on the Cameras
 * page (/cameras).  Clicking a camera card here navigates to
 * /cameras?selected={name} so the user lands directly on that camera's detail.
 */

import { useNavigate } from 'react-router-dom';
import { ServiceStatusCard } from '@/components/status/ServiceStatusCard';
import { CameraStatusGrid } from '@/components/status/CameraStatusGrid';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { SupportCard } from '@/components/common/SupportCard';
import type { CameraStatus } from '@/types/status';

/**
 * Main monitoring dashboard — simplified to status cards only.
 * Camera config and detail are delegated to CamerasPage.
 */
export function DashboardPage() {
  const navigate = useNavigate();

  /**
   * Navigate to the Cameras page with the selected camera pre-opened in the
   * detail panel so the user doesn't lose context.
   */
  function handleCameraClick(camera: CameraStatus) {
    navigate(`/cameras?selected=${encodeURIComponent(camera.name)}`);
  }

  return (
    <div className="space-y-5">
      <ErrorBoundary>
        <ServiceStatusCard />
      </ErrorBoundary>

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          Cameras
        </h2>
        <ErrorBoundary>
          <CameraStatusGrid onCameraClick={handleCameraClick} />
        </ErrorBoundary>
      </div>

      {/* Support card — dismissible, stays hidden after first close */}
      <SupportCard />
    </div>
  );
}
