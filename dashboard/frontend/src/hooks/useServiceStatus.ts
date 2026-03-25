/**
 * useServiceStatus — service status via polling /api/status.
 *
 * Polls every 15 seconds using React Query. The store is the single source
 * of truth so all status consumers stay in sync.
 */

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useStore } from '@/store';
import { getStatus } from '@/api/status';
import type { ServiceStatus } from '@/types/status';

/** React Query key for polled status. */
export const STATUS_QUERY_KEY = ['status'] as const;

/**
 * Hook that returns the current service status, polling /api/status every 15s.
 *
 * @returns The latest ServiceStatus from the store, or null if not yet loaded.
 */
export function useServiceStatus(): {
  status: ServiceStatus | null;
  isLoading: boolean;
} {
  const setStatus = useStore((s) => s.setStatus);
  const status = useStore((s) => s.status);

  const { data: polledStatus, isLoading } = useQuery({
    queryKey: STATUS_QUERY_KEY,
    queryFn: getStatus,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  // Push polled data into the store so all consumers see it
  useEffect(() => {
    if (polledStatus) {
      setStatus(polledStatus);
    }
  }, [polledStatus, setStatus]);

  return {
    status,
    isLoading: status === null && isLoading,
  };
}
