/**
 * DashboardPage — live security monitoring hub.
 *
 * Redesigned from a config-heavy admin panel into a reactive status dashboard.
 * Five sections, top to bottom:
 *
 *   1. System Hero        — full-width status card with pulsing dot, headline,
 *                           stat row, and most-recent detection event.
 *   2. Live Camera Grid   — visual card grid; clicking navigates to /cameras.
 *   3. Recent Activity    — stacked detection event feed derived from status API.
 *   4. Quick Actions      — three large nav buttons to the Tests page.
 *   5. Support Banner     — dismissible "consider supporting" card.
 *
 * No new API calls — all data flows from `useServiceStatus()` and
 * `useConfigQuery()` which are already polling on a shared interval.
 */

import { useNavigate } from 'react-router-dom';
import { ServiceStatusCard } from '@/components/status/ServiceStatusCard';
import { CameraStatusGrid } from '@/components/status/CameraStatusGrid';
import { RecentActivity } from '@/components/status/RecentActivity';
import { QuickActions } from '@/components/status/QuickActions';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { SupportCard } from '@/components/common/SupportCard';
import type { CameraStatus } from '@/types/status';

/**
 * Main monitoring dashboard — reactive status-first layout.
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
    <div className="space-y-6">

      {/* Section 1 — System Hero */}
      <ErrorBoundary>
        <ServiceStatusCard />
      </ErrorBoundary>

      {/* Section 2 — Live Camera Grid */}
      <div>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-600">
          Live Cameras
        </h2>
        <ErrorBoundary>
          <CameraStatusGrid onCameraClick={handleCameraClick} />
        </ErrorBoundary>
      </div>

      {/* Section 3 — Recent Activity */}
      <ErrorBoundary>
        <RecentActivity />
      </ErrorBoundary>

      {/* Section 4 — Quick Actions */}
      <div>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-600">
          Quick Actions
        </h2>
        <QuickActions />
      </div>

      {/* Section 5 — Support Banner */}
      <SupportCard />

    </div>
  );
}
