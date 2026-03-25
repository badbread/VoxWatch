/**
 * DashboardPage — main landing page with status overview, camera grid,
 * and clickable camera quick-config panel.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  X,
  Volume2,
  Wand2,
  Camera as CameraIcon,
  Clock,
  Mic,
  Shield,
  Zap,
  DollarSign,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { ServiceStatusCard } from '@/components/status/ServiceStatusCard';
import { CameraStatusGrid } from '@/components/status/CameraStatusGrid';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { SupportCard } from '@/components/common/SupportCard';
import { useConfigQuery } from '@/hooks/useConfig';
import { COST_MAP, formatCost, costColor } from '@/constants/aiCosts';
import { formatScheduleLabel } from '@/utils/formatters';
import type { CameraStatus } from '@/types/status';

/**
 * Main monitoring dashboard page with camera quick-config popup.
 */
export function DashboardPage() {
  const [selectedCamera, setSelectedCamera] = useState<CameraStatus | null>(null);
  const { data: config } = useConfigQuery();

  const scheduleLabel = formatScheduleLabel(config?.conditions?.active_hours);

  const cooldown = config?.conditions?.cooldown_seconds ?? 60;

  // Cost per detection
  const primaryKey = config?.ai?.primary
    ? `${config.ai.primary.provider}:${config.ai.primary.model}`
    : null;
  const primaryCost = primaryKey ? COST_MAP[primaryKey] ?? null : null;
  const isOllama = config?.ai?.primary?.provider === 'ollama';

  return (
    <div className="space-y-5">
      <ErrorBoundary>
        <ServiceStatusCard />
      </ErrorBoundary>

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          Cameras
        </h2>
        <div className="flex gap-4">
          {/* Camera grid */}
          <div className={cn('flex-1 min-w-0', selectedCamera && 'hidden sm:block')}>
            <ErrorBoundary>
              <CameraStatusGrid onCameraClick={setSelectedCamera} selectedName={selectedCamera?.name} />
            </ErrorBoundary>
          </div>

          {/* Quick-config panel */}
          {selectedCamera && (
            <div className="w-full sm:w-80 lg:w-96 flex-shrink-0">
              <div className="sticky top-4 rounded-xl border border-gray-200 bg-white dark:border-gray-700/50 dark:bg-gray-900 shadow-lg overflow-hidden">
                {/* Header */}
                <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700/50">
                  <div className="flex items-center gap-2">
                    <CameraIcon className="h-4 w-4 text-blue-500" />
                    <span className="font-semibold text-gray-900 dark:text-gray-100">
                      {selectedCamera.name}
                    </span>
                  </div>
                  <button
                    onClick={() => setSelectedCamera(null)}
                    className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-300"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                <div className="p-4 space-y-4">
                  {/* Status summary */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 text-sm">
                      <div className={cn(
                        'h-2 w-2 rounded-full',
                        selectedCamera.enabled ? 'bg-green-500' : 'bg-gray-400',
                      )} />
                      <span className={cn(
                        'font-medium',
                        selectedCamera.enabled
                          ? 'text-green-700 dark:text-green-400'
                          : 'text-gray-500 dark:text-gray-400',
                      )}>
                        {selectedCamera.enabled ? 'VoxWatch Enabled' : 'Not Configured'}
                      </span>
                    </div>

                    {selectedCamera.enabled && (
                      <div className="grid grid-cols-2 gap-2">
                        <div className="rounded-lg bg-gray-50 p-2.5 dark:bg-gray-800/50">
                          <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                            <Clock className="h-3 w-3 text-cyan-500" />
                            Schedule
                          </div>
                          <p className="mt-0.5 text-sm font-medium text-cyan-600 dark:text-cyan-400">
                            {scheduleLabel}
                          </p>
                        </div>
                        <div className="rounded-lg bg-gray-50 p-2.5 dark:bg-gray-800/50">
                          <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                            <Shield className="h-3 w-3 text-purple-500" />
                            Cooldown
                          </div>
                          <p className="mt-0.5 text-sm font-medium text-purple-600 dark:text-purple-400">
                            {cooldown}s
                          </p>
                        </div>
                        <div className="rounded-lg bg-gray-50 p-2.5 dark:bg-gray-800/50">
                          <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                            <Mic className="h-3 w-3 text-amber-500" />
                            Audio
                          </div>
                          <p className="mt-0.5 text-sm font-medium text-amber-600 dark:text-amber-400">
                            {selectedCamera.has_backchannel ? 'Confirmed' : 'via go2rtc'}
                          </p>
                        </div>
                        <div className="rounded-lg bg-gray-50 p-2.5 dark:bg-gray-800/50">
                          <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                            <DollarSign className="h-3 w-3 text-emerald-500" />
                            Cost/Detection
                          </div>
                          <p className={cn('mt-0.5 text-sm font-medium', isOllama ? 'italic text-green-600 dark:text-green-400' : costColor(primaryCost ?? 0))}>
                            {isOllama ? 'Free (local)' : primaryCost != null ? formatCost(primaryCost) : config?.ai?.primary?.model ?? 'N/A'}
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Last detection */}
                    {selectedCamera.last_detection_at && (
                      <div className="rounded-lg bg-rose-50 p-2.5 dark:bg-rose-950/20">
                        <div className="flex items-center gap-1.5 text-xs text-rose-500">
                          <Zap className="h-3 w-3" />
                          Last Detection
                        </div>
                        <p className="mt-0.5 text-sm font-medium text-rose-700 dark:text-rose-300">
                          {new Date(selectedCamera.last_detection_at).toLocaleString()}
                          {selectedCamera.last_latency_ms != null && (
                            <span className="ml-2 font-mono text-xs">
                              ({(selectedCamera.last_latency_ms / 1000).toFixed(1)}s)
                            </span>
                          )}
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Action buttons */}
                  <div className="space-y-2">
                    {!selectedCamera.enabled && (
                      <Link
                        to={`/config?tab=cameras`}
                        className="flex items-center justify-center gap-2 rounded-lg bg-primary-600 px-3 py-2.5 text-sm font-medium text-white hover:bg-primary-700 transition-colors"
                      >
                        <Wand2 className="h-3.5 w-3.5" />
                        Configure Camera
                      </Link>
                    )}
                    {selectedCamera.enabled && (
                      <Link
                        to="/audio"
                        className="flex items-center justify-center gap-2 rounded-lg border border-blue-300 bg-blue-50 px-3 py-2.5 text-sm font-medium text-blue-700 hover:bg-blue-100 dark:border-blue-700 dark:bg-blue-950/30 dark:text-blue-300 dark:hover:bg-blue-950/50 transition-colors"
                      >
                        <Volume2 className="h-3.5 w-3.5" />
                        Test Audio
                      </Link>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Support card — dismissible, stays hidden after first close */}
      <SupportCard />
    </div>
  );
}
