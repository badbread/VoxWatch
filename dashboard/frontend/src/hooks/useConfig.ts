/**
 * useConfig — React Query hooks for VoxWatch configuration CRUD.
 *
 * Provides:
 * - useConfigQuery: fetches and caches the current config
 * - useConfigMutation: saves a modified config with optimistic updates
 * - useValidateConfigMutation: validates without saving (for live feedback)
 * - useReloadConfigMutation: instructs the backend to reload config from disk
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getConfig, saveConfig, validateConfig, reloadConfig } from '@/api/config';
import { useStore } from '@/store';
import type { VoxWatchConfig } from '@/types/config';

/** React Query key for the config. */
export const CONFIG_QUERY_KEY = ['config'] as const;

/**
 * Fetches and caches the current VoxWatch configuration.
 *
 * Stale time is set high (5 minutes) since config changes are rare and always
 * triggered by explicit user action — not background refreshes.
 */
export function useConfigQuery() {
  return useQuery({
    queryKey: CONFIG_QUERY_KEY,
    queryFn: getConfig,
    staleTime: 5 * 60 * 1000,
    retry: 2,
  });
}

/**
 * Mutation hook for saving a modified configuration.
 *
 * On success, invalidates the config query so the next read reflects the
 * persisted state. Shows a toast on both success and failure.
 */
export function useConfigMutation() {
  const queryClient = useQueryClient();
  const addToast = useStore((s) => s.addToast);

  return useMutation({
    mutationFn: saveConfig,
    onSuccess: (result) => {
      // The PUT /api/config returns { message, config, warnings } on success
      // and ConfigValidationResult { valid, errors, warnings } on validation failure.
      // Check for both response shapes.
      const isValid = 'valid' in result ? result.valid : true;
      if (isValid) {
        void queryClient.invalidateQueries({ queryKey: CONFIG_QUERY_KEY });
        addToast('Configuration saved successfully.', 'success');
      } else {
        addToast(
          `Configuration has ${'errors' in result ? result.errors.length : 0} validation error(s).`,
          'error',
        );
      }
    },
    onError: () => {
      addToast('Failed to save configuration. Check the backend logs.', 'error');
    },
  });
}

/**
 * Mutation hook for validating a configuration without saving.
 *
 * Returns the validation result in `data` after mutation settles.
 * No toast is shown — the caller handles validation UI inline.
 */
export function useValidateConfigMutation() {
  return useMutation({
    mutationFn: (config: VoxWatchConfig) => validateConfig(config),
  });
}

/**
 * Mutation hook for reloading config from disk without a full restart.
 *
 * Shows a success toast on completion.
 */
export function useReloadConfigMutation() {
  const addToast = useStore((s) => s.addToast);
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: reloadConfig,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CONFIG_QUERY_KEY });
      addToast('Configuration reloaded from disk.', 'success');
    },
    onError: () => {
      addToast('Failed to reload configuration.', 'error');
    },
  });
}
