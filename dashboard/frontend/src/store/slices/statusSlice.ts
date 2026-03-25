/**
 * Status slice — Zustand state for the VoxWatch service status.
 *
 * Updated by WebSocket status_update messages and by the polling fallback in
 * useServiceStatus. Components read from this slice via the root store.
 */

import type { ServiceStatus } from '@/types/status';

/** Shape of the status slice within the root store. */
export interface StatusSlice {
  /** Latest service status snapshot, or null if not yet received. */
  status: ServiceStatus | null;
  /** ISO 8601 timestamp of the last successful status update. */
  lastUpdatedAt: string | null;
  /** Actions */
  setStatus: (status: ServiceStatus) => void;
  clearStatus: () => void;
}

/** Zustand slice factory for status state. */
export const createStatusSlice = (
  set: (
    partial:
      | Partial<StatusSlice>
      | ((state: StatusSlice) => Partial<StatusSlice>),
  ) => void,
): StatusSlice => ({
  status: null,
  lastUpdatedAt: null,

  setStatus: (status: ServiceStatus) =>
    set({ status, lastUpdatedAt: new Date().toISOString() }),

  clearStatus: () => set({ status: null, lastUpdatedAt: null }),
});
