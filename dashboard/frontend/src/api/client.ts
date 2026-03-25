/**
 * Axios HTTP client instance for the VoxWatch Dashboard.
 *
 * All API modules import from this file so base URL and interceptors are
 * configured in one place. In development, Vite proxies /api → localhost:33344
 * so no CORS headers are required. In production, the same nginx reverse proxy
 * routes /api to the backend container.
 */

import axios, { type AxiosError } from 'axios';

/** Shared Axios instance with JSON defaults and a sensible timeout. */
const apiClient = axios.create({
  baseURL: '/api',
  timeout: 15_000,
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
});

// ---------------------------------------------------------------------------
// Response interceptor — normalise error shapes
// ---------------------------------------------------------------------------

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorBody>) => {
    const status = error.response?.status;
    const detail = error.response?.data?.detail;

    // Build a human-readable message from the backend detail field when available
    const message =
      typeof detail === 'string'
        ? detail
        : typeof detail === 'object' && detail !== null
          ? JSON.stringify(detail)
          : error.message ?? 'An unexpected error occurred.';

    // Attach a normalised message to the error so callers don't need to dig
    const enhanced = error as ApiError;
    enhanced.userMessage = message;
    enhanced.statusCode = status;

    return Promise.reject(enhanced);
  },
);

// ---------------------------------------------------------------------------
// Extended error type
// ---------------------------------------------------------------------------

/** Shape of FastAPI validation / HTTP error response bodies. */
interface ApiErrorBody {
  detail?: string | Record<string, unknown>;
}

/** Axios error extended with pre-formatted user-facing fields. */
export interface ApiError extends AxiosError<ApiErrorBody> {
  /** Human-readable error message suitable for toast notifications. */
  userMessage: string;
  /** HTTP status code (undefined for network errors). */
  statusCode: number | undefined;
}

/** Type guard to check whether a caught error is an ApiError. */
export function isApiError(err: unknown): err is ApiError {
  return (
    typeof err === 'object' &&
    err !== null &&
    'userMessage' in err &&
    'isAxiosError' in err &&
    (err as ApiError).isAxiosError === true
  );
}

export default apiClient;
