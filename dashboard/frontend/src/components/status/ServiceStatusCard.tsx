/**
 * ServiceStatusCard — displays Frigate and go2rtc reachability with
 * color-coded version numbers and stats.
 */

import { Server, Video, DollarSign } from 'lucide-react';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { CardSkeleton } from '@/components/common/LoadingSpinner';
import { useServiceStatus } from '@/hooks/useServiceStatus';
import { useConfigQuery } from '@/hooks/useConfig';
import { COST_MAP } from '@/constants/aiCosts';
import type { BadgeVariant } from '@/components/common/Badge';

function reachableVariant(reachable: boolean): BadgeVariant {
  return reachable ? 'connected' : 'error';
}

/**
 * Status card showing Frigate and go2rtc health with colorful metadata.
 */
export function ServiceStatusCard() {
  const { status, isLoading } = useServiceStatus();
  const { data: config } = useConfigQuery();

  if (isLoading || !status) {
    return <CardSkeleton />;
  }

  const { frigate, go2rtc } = status;

  // Cost estimate from config
  const aiKey = config?.ai?.primary
    ? `${config.ai.primary.provider}:${config.ai.primary.model}`
    : null;
  const costPerDetection = aiKey ? (COST_MAP[aiKey] ?? null) : null;
  const monthlyCost = costPerDetection != null ? costPerDetection * 30 * 30 : null;

  return (
    <Card title="System Status" subtitle="External service connectivity">
      <ul className="space-y-2">
        {/* Frigate */}
        <li className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2.5 dark:bg-gray-800/50">
          <div className="flex items-center gap-2.5">
            <Video className="h-4 w-4 flex-shrink-0 text-blue-400" aria-hidden="true" />
            <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
              Frigate NVR
            </span>
            {frigate.version && (
              <span className="rounded bg-blue-100 px-1.5 py-0.5 font-mono text-xs font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
                v{frigate.version}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {frigate.reachable && frigate.camera_count != null && (
              <span className="text-xs font-medium text-cyan-600 dark:text-cyan-400">
                {frigate.camera_count} camera{frigate.camera_count !== 1 ? 's' : ''}
              </span>
            )}
            <Badge
              variant={reachableVariant(frigate.reachable)}
              label={frigate.reachable ? 'Reachable' : (frigate.error ?? 'Unreachable')}
              size="xs"
              dot
            />
          </div>
        </li>

        {/* go2rtc */}
        <li className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2.5 dark:bg-gray-800/50">
          <div className="flex items-center gap-2.5">
            <Server className="h-4 w-4 flex-shrink-0 text-purple-400" aria-hidden="true" />
            <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
              go2rtc
            </span>
            {go2rtc.version && go2rtc.version !== 'unknown' && (
              <span className="rounded bg-purple-100 px-1.5 py-0.5 font-mono text-xs font-medium text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">
                v{go2rtc.version}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {go2rtc.reachable && go2rtc.stream_count != null && (
              <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
                {go2rtc.stream_count} stream{go2rtc.stream_count !== 1 ? 's' : ''}
              </span>
            )}
            <Badge
              variant={reachableVariant(go2rtc.reachable)}
              label={go2rtc.reachable ? 'Reachable' : (go2rtc.error ?? 'Unreachable')}
              size="xs"
              dot
            />
          </div>
        </li>
        {/* AI Cost Estimate */}
        {costPerDetection != null && (
          <li className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2.5 dark:bg-gray-800/50">
            <div className="flex items-center gap-2.5">
              <DollarSign className="h-4 w-4 flex-shrink-0 text-emerald-400" aria-hidden="true" />
              <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                AI Cost
              </span>
              <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                {config?.ai?.primary?.model}
              </span>
            </div>
            <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400">
              {costPerDetection === 0
                ? 'Free (local)'
                : `~$${monthlyCost!.toFixed(2)}/mo (30/day)`}
            </span>
          </li>
        )}
      </ul>
    </Card>
  );
}
