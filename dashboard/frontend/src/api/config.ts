/**
 * Config API — CRUD operations for the VoxWatch YAML configuration.
 *
 * The backend reads and writes config.yaml; the frontend communicates with it
 * via these typed wrappers. All functions return Promises and throw ApiError on
 * failure, so React Query can handle loading/error state automatically.
 */

import apiClient from './client';
import type { VoxWatchConfig, ConfigValidationResult } from '@/types/config';

/**
 * Fetches the current parsed configuration from the backend.
 *
 * @returns The full VoxWatchConfig object
 */
export async function getConfig(): Promise<VoxWatchConfig> {
  const response = await apiClient.get<VoxWatchConfig>('/config');
  return response.data;
}

/**
 * Persists a modified configuration object to the backend (writes config.yaml).
 *
 * The backend validates the config before writing and returns a validation
 * result. A successful write returns `{ valid: true, errors: [] }`.
 *
 * @param config - The full updated config object
 * @returns Validation result from the backend
 */
export async function saveConfig(
  config: VoxWatchConfig,
): Promise<ConfigValidationResult> {
  const response = await apiClient.put<ConfigValidationResult>(
    '/config',
    config,
  );
  return response.data;
}

/**
 * Asks the backend to validate a config object without writing it.
 *
 * Useful for real-time validation before enabling the Save button.
 *
 * @param config - The config object to validate
 * @returns Validation result (no side effects)
 */
export async function validateConfig(
  config: VoxWatchConfig,
): Promise<ConfigValidationResult> {
  const response = await apiClient.post<ConfigValidationResult>(
    '/config/validate',
    config,
  );
  return response.data;
}

/**
 * Instructs the backend to reload configuration from disk without restart.
 *
 * @returns Confirmation message from the backend
 */
export async function reloadConfig(): Promise<{ message: string }> {
  const response = await apiClient.post<{ message: string }>(
    '/config/reload',
  );
  return response.data;
}
