/**
 * Wizard API — camera setup wizard backend calls.
 *
 * Three endpoints drive the wizard flow:
 *   1. detectCamera  — probe a camera's go2rtc stream for backchannel support
 *                      and available audio codecs.
 *   2. testWizardAudio — push a test tone through the backchannel and return
 *                        success / response timing.
 *   3. saveWizardCamera — write the finished camera config to VoxWatch and
 *                         optionally enable it immediately.
 *
 * All functions throw an ApiError (from client.ts) on non-2xx responses so
 * callers can display error.userMessage directly in the UI.
 */

import apiClient from './client';

// ---------------------------------------------------------------------------
// Request / response types
// ---------------------------------------------------------------------------

/** Request body for the camera detection probe. */
export interface DetectRequest {
  /** Frigate / go2rtc camera name to probe. */
  camera_name: string;
}

/** Result of the camera detection probe. */
export interface DetectResponse {
  /** Camera name echoed back. */
  camera_name: string;
  /** go2rtc stream name resolved for this camera. */
  stream_name: string;
  /** Whether go2rtc found an RTSP backchannel track. */
  has_backchannel: boolean;
  /**
   * Raw codec strings reported by go2rtc (e.g. ["PCMU/8000", "PCMA/8000"]).
   * Empty when no backchannel is present.
   */
  codecs: string[];
  /**
   * The codec VoxWatch recommends trying first (e.g. "pcm_mulaw").
   * Null when the backend cannot make a recommendation.
   */
  recommended_codec: string | null;
  /** Whether Frigate reports this camera as online. */
  frigate_online?: boolean;
  /** Frigate detection FPS at probe time. */
  fps?: number;
  /** URL of the latest Frigate snapshot for the thumbnail. */
  snapshot_url?: string;
}

/** Request body to run a guided audio test push. */
export interface WizardTestRequest {
  /** Camera name to push the test tone through. */
  camera_name: string;
  /** go2rtc stream name resolved during detection. */
  stream_name: string;
  /**
   * Audio codec to use for this test (e.g. "pcm_mulaw", "pcm_alaw").
   * Must be a codec supported by go2rtc's backchannel.
   */
  codec: string;
  /**
   * Seconds to wait after opening the backchannel before sending audio.
   * Allows slow cameras time to negotiate the stream. Range: 1–5.
   */
  warmup_delay: number;
  /** Audio sample rate in Hz (default 8000). */
  sample_rate?: number;
}

/** Result of a wizard audio test push. */
export interface WizardTestResponse {
  /** True when the push completed without a transport error. */
  success: boolean;
  /** Human-readable result description for display in the UI. */
  message: string;
  /** Round-trip time from request to audio delivery confirmation, in ms. */
  response_time_ms: number;
}

/** Request body to save a completed wizard configuration. */
export interface WizardSaveRequest {
  /** Camera name to write to config. */
  camera_name: string;
  /** go2rtc stream name for this camera. */
  go2rtc_stream: string;
  /** Audio codec override (e.g. "pcm_mulaw"). Optional — backend picks a default. */
  audio_codec?: string;
  /** Sample rate override in Hz. Optional. */
  sample_rate?: number;
  /** Channel count override. Optional. */
  channels?: number;
  /** Whether to enable this camera in VoxWatch immediately. */
  enabled: boolean;
  /**
   * Free-text description of the scene / location for the AI prompt context.
   * E.g. "front driveway, residential, daytime use only".
   */
  scene_context?: string;
}

/** Result of saving a wizard camera configuration. */
export interface WizardSaveResponse {
  /** True when the config was written and VoxWatch accepted it. */
  success: boolean;
  /** Human-readable result description. */
  message: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Probe a camera's go2rtc stream for backchannel support and codec info.
 *
 * Used in the Analysis step to populate codec badges and the recommended
 * starting codec for the audio test.
 *
 * @param req - Camera name to probe
 * @returns Stream name, backchannel flag, codecs, and Frigate stats
 */
export async function detectCamera(req: DetectRequest): Promise<DetectResponse> {
  const response = await apiClient.post<DetectResponse>('/wizard/detect', req);
  return response.data;
}

/**
 * Push a test tone through the camera's backchannel using the given codec.
 *
 * The backend opens the go2rtc backchannel, waits `warmup_delay` seconds,
 * then sends a short audio clip. The operator listens at the camera and
 * reports whether they heard sound.
 *
 * @param req - Camera, stream, codec, and warmup settings
 * @returns Success flag, message, and round-trip response time
 */
export async function testWizardAudio(
  req: WizardTestRequest,
): Promise<WizardTestResponse> {
  const response = await apiClient.post<WizardTestResponse>(
    '/wizard/test-audio',
    req,
  );
  return response.data;
}

/**
 * Write the completed wizard configuration to VoxWatch config and optionally
 * enable the camera.
 *
 * Called in the Configure step after the operator has confirmed audio works
 * and filled in the optional scene context field.
 *
 * @param req - Full camera config including codec, stream, and enabled flag
 * @returns Success flag and status message
 */
export async function saveWizardCamera(
  req: WizardSaveRequest,
): Promise<WizardSaveResponse> {
  const response = await apiClient.post<WizardSaveResponse>(
    '/wizard/save',
    req,
  );
  return response.data;
}
