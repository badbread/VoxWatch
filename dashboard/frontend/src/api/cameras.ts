/**
 * Cameras API — camera list and snapshot retrieval.
 *
 * Snapshots are fetched from Frigate via the backend proxy to avoid exposing
 * the Frigate API port directly to the browser.
 */

import apiClient from './client';
import type { CameraStatus, CameraIdentifyResult } from '@/types/status';

/**
 * Fetches the list of configured cameras with their current status.
 *
 * @returns Array of camera status objects
 */
export async function getCameras(): Promise<CameraStatus[]> {
  const response = await apiClient.get<CameraStatus[]>('/cameras');
  return response.data;
}

/**
 * Probes a camera via ONVIF and cross-references its model against the
 * VoxWatch compatibility database.
 *
 * Makes a POST to /api/cameras/{name}/identify which:
 *   1. Resolves the camera IP from the go2rtc RTSP stream URL.
 *   2. Sends an ONVIF GetDeviceInformation SOAP request.
 *   3. Matches the model string against KNOWN_CAMERAS.
 *
 * @param cameraName - Frigate/go2rtc camera name
 * @returns Identification and compatibility result
 */
export async function identifyCamera(
  cameraName: string,
): Promise<CameraIdentifyResult> {
  const response = await apiClient.post<CameraIdentifyResult>(
    `/cameras/${encodeURIComponent(cameraName)}/identify`,
  );
  return response.data;
}

/**
 * Returns a snapshot URL and timestamp for a camera.
 *
 * The URL points to the backend proxy endpoint which returns raw JPEG bytes
 * from Frigate. A cache-busting timestamp is appended so the browser
 * doesn't serve a stale cached frame.
 *
 * @param cameraName - Frigate camera name
 * @returns Object with the snapshot URL and current timestamp
 */
export async function getCameraSnapshot(
  cameraName: string,
): Promise<{ url: string; timestamp: string }> {
  // The backend serves raw JPEG at this path — we just build the URL
  // and append a timestamp to bust the browser cache on each refresh.
  const baseUrl = apiClient.defaults.baseURL ?? '/api';
  const url = `${baseUrl}/cameras/${cameraName}/snapshot?t=${Date.now()}`;
  return { url, timestamp: new Date().toISOString() };
}
