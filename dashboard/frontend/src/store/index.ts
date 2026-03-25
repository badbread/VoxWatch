/**
 * Root Zustand store — combines all state slices.
 *
 * Use the typed `useStore` hook in components to access state and actions.
 * Slices are composed via Zustand's slice pattern so each slice file remains
 * independently readable without knowing about the full store shape.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import {
  createStatusSlice,
  type StatusSlice,
} from './slices/statusSlice';
import {
  createToastSlice,
  type ToastSlice,
} from './slices/toastSlice';

/** Full root store type — union of all slice types. */
export type RootStore = StatusSlice & ToastSlice;

/**
 * The root Zustand store with Redux DevTools support in development.
 *
 * @example
 *   const status = useStore((s) => s.status);
 *   const addToast = useStore((s) => s.addToast);
 */
export const useStore = create<RootStore>()(
  devtools(
    (set) => ({
      ...createStatusSlice(set as Parameters<typeof createStatusSlice>[0]),
      ...createToastSlice(set as Parameters<typeof createToastSlice>[0]),
    }),
    { name: 'VoxWatch' },
  ),
);
