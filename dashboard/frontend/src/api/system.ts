/**
 * System API — service log retrieval.
 *
 * Thin wrapper over the /api/system/logs endpoint that the Tests page uses
 * to display recent VoxWatch container log output.
 */

import apiClient from './client';

/** A single parsed log entry returned by GET /api/system/logs. */
export interface LogEntry {
  /** ISO 8601 timestamp of the log line, or null if unparseable. */
  timestamp: string | null;
  /** Severity level (ERROR, WARNING, INFO, DEBUG). */
  level: string;
  /** Logger name (e.g. "voxwatch.audio", "dashboard.router.system"). */
  logger: string;
  /** Human-readable message body. */
  message: string;
  /** Raw original line (useful for lines that could not be parsed). */
  raw: string;
}

/** Response shape from GET /api/system/logs. */
export interface LogsResponse {
  /** Ordered list of log entries, oldest first. */
  entries: LogEntry[];
  /** Total lines read from the log file before filtering. */
  lines_read: number;
  /** Absolute path of the log file that was read. */
  log_file: string;
  /** Error message when the log file could not be opened, otherwise null. */
  error: string | null;
}

/**
 * Fetch recent log lines from the VoxWatch service log.
 *
 * @param lines - Maximum number of lines to return (default 50, max 500).
 * @param level - Filter to a specific severity level; "all" returns everything.
 * @returns Parsed log entries and metadata about the log file.
 */
export async function getLogs(
  lines: number = 50,
  level: string = 'all',
): Promise<LogsResponse> {
  const response = await apiClient.get<LogsResponse>('/system/logs', {
    params: { lines, level },
  });
  return response.data;
}
