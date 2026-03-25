/**
 * Status API — service health, runtime status, and audio preview.
 *
 * The /api/status endpoint is polled by the useServiceStatus hook as a
 * fallback for when the WebSocket connection is unavailable.
 *
 * The previewAudio function hits POST /api/audio/preview and returns a
 * WAV Blob for in-browser playback — no camera speaker is involved.
 */

import apiClient from './client';
import type { ServiceStatus } from '@/types/status';

/**
 * Fetches the current service status snapshot from the backend.
 *
 * Includes run state, uptime, camera health, and dependency health.
 *
 * @returns Full ServiceStatus object
 */
export async function getStatus(): Promise<ServiceStatus> {
  const response = await apiClient.get<ServiceStatus>('/status');
  return response.data;
}

/** AI provider test request. */
export interface AiTestRequest {
  provider: string;
  model: string;
  api_key?: string;
  host?: string;
}

/** AI provider test response. */
export interface AiTestResponse {
  success: boolean;
  provider: string;
  model: string;
  message: string;
  response_time_ms?: number;
}

/**
 * Test connectivity to an AI vision provider.
 * Sends a minimal prompt to verify API key, model, and network connectivity.
 */
export async function testAiProvider(req: AiTestRequest): Promise<AiTestResponse> {
  const response = await apiClient.post<AiTestResponse>('/system/test-ai', req);
  return response.data;
}

/** TTS voice test request — provider config + sample text. */
export interface TtsTestRequest {
  /** TTS engine identifier (e.g. "kokoro", "piper", "elevenlabs"). */
  engine: string;
  /** Sample text to synthesize. Defaults to a standard test phrase. */
  text?: string;
  /** Provider-specific config fields (API keys, voice IDs, etc.). */
  config: Record<string, string | number | undefined>;
}

/** TTS voice test response. */
export interface TtsTestResponse {
  success: boolean;
  engine: string;
  message: string;
  /** Synthesis duration in milliseconds. */
  synthesis_ms?: number;
}

/**
 * Synthesize a short sample phrase with the given TTS provider config.
 * Used by the TTS config form "Test Voice" button to verify credentials
 * and hear the selected voice before saving.
 */
export async function testTtsVoice(req: TtsTestRequest): Promise<TtsTestResponse> {
  const response = await apiClient.post<TtsTestResponse>('/system/test-tts', req);
  return response.data;
}

// ---------------------------------------------------------------------------
// Audio preview API
// ---------------------------------------------------------------------------

/** Request body for POST /api/audio/preview. */
export interface AudioPreviewRequest {
  /** Persona name from the backend PERSONAS dict (e.g. "mafioso"). */
  persona: string;
  /** TTS voice identifier (Kokoro voice ID, Piper model name, etc.). */
  voice: string;
  /** TTS provider: "kokoro" | "piper" | "espeak". */
  provider: string;
  /** Remote TTS server base URL (required for Kokoro remote). */
  provider_host?: string | undefined;
  /** Custom deterrent message.  Omit to use the persona-specific sample. */
  message?: string | undefined;
  /** Playback speed multiplier (0.25–4.0, default 1.0). */
  speed?: number | undefined;
}

/** Result from previewAudio — includes the WAV blob and synthesis latency. */
export interface AudioPreviewResult {
  /** Raw WAV audio blob.  Pass to URL.createObjectURL() for playback. */
  blob: Blob;
  /** Synthesis latency in milliseconds from the X-Generation-Time header. */
  generationTimeMs: number;
}

/**
 * Generate a browser-playable audio preview for the given persona + voice.
 *
 * POSTs to /api/audio/preview with responseType "blob" so the raw WAV bytes
 * come back as a Blob that can be played via the Web Audio API without any
 * base64 encoding overhead.
 *
 * @param req  Preview parameters (persona, voice, provider, optional message).
 * @returns    AudioPreviewResult with the WAV blob and generation latency.
 * @throws     ApiError on network failure or server error (4xx / 5xx).
 */
export async function previewAudio(req: AudioPreviewRequest): Promise<AudioPreviewResult> {
  const response = await apiClient.post<Blob>('/audio/preview', req, {
    responseType: 'blob',
    // Synthesis can take a few seconds on a loaded server — extend timeout.
    timeout: 35_000,
  });

  // Read synthesis latency from the custom response header.
  const headerMs = response.headers['x-generation-time'];
  const generationTimeMs = headerMs ? parseInt(headerMs, 10) : 0;

  return { blob: response.data, generationTimeMs };
}

/** Request body for POST /api/audio/generate-intro. */
export interface GenerateIntroRequest {
  /** Intro phrase text. Supports {agency} template token. */
  text: string;
  /** TTS provider override (kokoro, elevenlabs, openai, cartesia, piper, espeak). */
  provider?: string;
  /** Provider-specific voice identifier. */
  voice?: string;
  /** Speed multiplier (0.25 – 4.0). Default 1.0. */
  speed?: number;
  /**
   * When true, the generated audio is persisted to
   * /data/audio/dispatch_intro_cached.wav for automatic reuse by the
   * live dispatch pipeline.
   */
  save?: boolean;
}

/** Result from generateIntroAudio. */
export interface GenerateIntroResult {
  /** Raw WAV Blob for in-browser playback. */
  blob: Blob;
  /** Synthesis latency in milliseconds. */
  generationTimeMs: number;
  /** Whether the audio was also saved to the cached path. */
  saved: boolean;
}

/**
 * POST /api/audio/generate-intro — Synthesise a dispatch channel intro and
 * optionally persist it for live pipeline reuse.
 *
 * Proxies to the VoxWatch Preview API (local TTS) with cloud provider
 * fallback handled in the dashboard.  Returns a WAV Blob for preview.
 */
export async function generateIntroAudio(
  req: GenerateIntroRequest,
): Promise<GenerateIntroResult> {
  const response = await apiClient.post<Blob>('/audio/generate-intro', req, {
    responseType: 'blob',
    timeout: 35_000,
  });

  const headerMs = response.headers['x-generation-time'];
  const generationTimeMs = headerMs ? parseInt(headerMs, 10) : 0;
  const saved = response.headers['x-intro-saved'] === 'true';

  return { blob: response.data, generationTimeMs, saved };
}

/** Result from uploadIntroAudio. */
export interface UploadIntroResult {
  /** Whether the upload was accepted and written to disk. */
  success: boolean;
  /** Absolute path where the file was saved (for use in dispatch.intro_audio). */
  path: string;
  /** File size in bytes. */
  size_bytes: number;
  /** Detected audio format (WAV, MP3, etc.). */
  format: string;
  /** Human-readable status message. */
  message: string;
}

/**
 * POST /api/audio/upload-intro — Upload a custom WAV/MP3 as the dispatch
 * channel intro.  Saves to /config/audio/dispatch_intro.wav.
 *
 * @param file - Audio file from a browser file input.
 */
export async function uploadIntroAudio(file: File): Promise<UploadIntroResult> {
  const form = new FormData();
  form.append('file', file);

  const response = await apiClient.post<UploadIntroResult>('/audio/upload-intro', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 30_000,
  });

  return response.data;
}
