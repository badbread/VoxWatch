/**
 * Audio API — manual test audio push.
 *
 * The test-push endpoint allows operators to verify camera audio is working
 * without waiting for a real detection event.
 */

import apiClient from './client';

/** Request body for a manual audio test push. */
export interface TestAudioRequest {
  /** Target camera name (must match a configured camera and go2rtc stream). */
  camera_name: string;
  /** Custom message text (defaults to a standard test phrase). */
  message?: string;
  /** Optional base URL of the VoxWatch audio HTTP server. */
  audio_server_url?: string;
}

/** Response body from a test audio push. */
export interface TestAudioResponse {
  success: boolean;
  camera: string;
  stream_name: string;
  message: string;
}

/**
 * Triggers a manual audio push to a camera speaker via go2rtc.
 *
 * @param request - Camera name, optional message, and optional audio server URL
 * @returns Result including success flag and human-readable message
 */
export async function testAudio(
  request: TestAudioRequest,
): Promise<TestAudioResponse> {
  const response = await apiClient.post<TestAudioResponse>(
    '/audio/test',
    request,
  );
  return response.data;
}
