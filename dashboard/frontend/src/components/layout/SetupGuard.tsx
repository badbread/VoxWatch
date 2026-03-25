/**
 * SetupGuard — route guard that redirects to /setup when config.yaml is missing.
 *
 * Wraps all authenticated routes inside the AppShell. On every page load it
 * fetches GET /api/setup/status. If config_exists is false the user is
 * immediately redirected to /setup so they can complete the first-run wizard.
 *
 * While the status check is in-flight a full-screen loading spinner is shown
 * to prevent a flash of the dashboard before the redirect fires.
 *
 * Once redirected to /setup the wizard route is rendered OUTSIDE this guard
 * (see App.tsx) so there is no circular redirect loop.
 */

import { Navigate, Outlet } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Shield, Loader } from 'lucide-react';
import { getSetupStatus } from '@/api/setup';

/**
 * Route wrapper that enforces first-run setup completion.
 *
 * Renders <Outlet /> (the normal app) only when config.yaml exists.
 * Otherwise redirects to /setup.
 *
 * @example
 *   // In App.tsx:
 *   <Route element={<SetupGuard />}>
 *     <Route element={<AppShell />}>
 *       ...main app routes...
 *     </Route>
 *   </Route>
 */
export function SetupGuard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['setup-status'],
    queryFn: getSetupStatus,
    // Don't retry aggressively — if the backend isn't up yet, bail fast
    retry: 1,
    retryDelay: 1000,
    // Mark stale immediately so a refresh always re-checks
    staleTime: 0,
  });

  // Backend not available yet — show loading screen
  if (isLoading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gray-950">
        <div className="flex flex-col items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600/20">
            <Shield className="h-7 w-7 text-blue-400" />
          </div>
          <Loader className="h-5 w-5 animate-spin text-blue-500" />
          <p className="text-sm text-gray-500">Checking configuration...</p>
        </div>
      </div>
    );
  }

  // Backend errored — allow through to the app so users aren't stuck.
  // The dashboard will show its own error state.
  if (isError || !data) {
    return <Outlet />;
  }

  // Config doesn't exist — redirect to the setup wizard
  if (!data.config_exists) {
    return <Navigate to="/setup" replace />;
  }

  // Config exists — render the normal app
  return <Outlet />;
}
