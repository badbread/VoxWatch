/**
 * Setup API — first-run wizard backend endpoints.
 *
 * Three endpoints drive the setup flow:
 *   GET  /api/setup/status   — check if config.yaml exists
 *   POST /api/setup/probe    — discover Frigate, go2rtc, and MQTT
 *   POST /api/setup/generate — write config.yaml and start VoxWatch
 */

import apiClient from './client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Response from GET /api/setup/status.
 * Tells the frontend whether the user needs to run the wizard.
 */
export interface SetupStatus {
  /** Whether config.yaml already exists on the filesystem. */
  config_exists: boolean;
  /** Whether setup has been completed at least once. */
  setup_complete: boolean;
  /** Whether Frigate credentials are present in the config. */
  frigate_configured: boolean;
  /** Whether MQTT credentials are present in the config. */
  mqtt_configured: boolean;
  /** Whether an AI provider is configured. */
  ai_configured: boolean;
  /** Whether at least one camera is enabled. */
  cameras_configured: boolean;
  /**
   * Value of the FRIGATE_HOST environment variable, if set.
   * Pre-fills the Frigate host input so Docker Compose users get a zero-effort setup.
   */
  frigate_host_env: string | null;
}

/**
 * Request body for POST /api/setup/probe.
 * All fields beyond frigate_host are optional — the backend fills in defaults.
 */
export interface ProbeRequest {
  /** Frigate hostname or IP address. Required. */
  frigate_host: string;
  /** Frigate API port (default 5000). */
  frigate_port?: number;
  /** go2rtc hostname (defaults to frigate_host). */
  go2rtc_host?: string;
  /** go2rtc API port (default 1984). */
  go2rtc_port?: number;
  /** MQTT broker hostname (defaults to frigate_host). */
  mqtt_host?: string;
  /** MQTT broker port (default 1883). */
  mqtt_port?: number;
  /** Optional MQTT username. */
  mqtt_user?: string | undefined;
  /** Optional MQTT password. */
  mqtt_password?: string | undefined;
}

/**
 * Response from POST /api/setup/probe.
 * Contains everything discovered about the services.
 */
export interface ProbeResult {
  /** Whether the Frigate API responded. */
  frigate_reachable: boolean;
  /** Frigate version string, or null if unreachable. */
  frigate_version: string | null;
  /** List of camera names registered in Frigate. */
  frigate_cameras: string[];
  /** Whether the go2rtc API responded. */
  go2rtc_reachable: boolean;
  /** go2rtc version string, or null if unreachable. */
  go2rtc_version: string | null;
  /** List of stream names registered in go2rtc. */
  go2rtc_streams: string[];
  /**
   * Per-camera backchannel information as reported by go2rtc.
   * Key is the stream name. Populated for any stream that has backchannel data.
   */
  backchannel_info: Record<string, { has_backchannel: boolean; codecs: string[] }>;
  /** Whether the MQTT broker accepted a test connection. */
  mqtt_reachable: boolean;
  /**
   * MQTT host extracted from Frigate's /api/config mqtt.host field.
   * Null when Frigate is unreachable or does not have mqtt.host configured.
   */
  mqtt_host_detected: string | null;
  /**
   * MQTT port extracted from Frigate's /api/config mqtt.port field.
   * Null when not available.
   */
  mqtt_port_detected: number | null;
  /** How long the entire probe took in milliseconds. */
  probe_duration_ms: number;
  /** Per-service error messages if any service was unreachable. */
  errors: Record<string, string>;
}

/**
 * Request body for POST /api/setup/generate.
 * Contains all information needed to write a complete config.yaml.
 */
export interface GenerateConfigRequest {
  /** Frigate API hostname. */
  frigate_host: string;
  /** Frigate API port. */
  frigate_port: number;
  /** go2rtc API hostname. */
  go2rtc_host: string;
  /** go2rtc API port. */
  go2rtc_port: number;
  /** MQTT broker hostname. */
  mqtt_host: string;
  /** MQTT broker port. */
  mqtt_port: number;
  /** MQTT username (empty string if not required). */
  mqtt_user: string;
  /** MQTT password (empty string if not required). */
  mqtt_password: string;
  /** MQTT event topic. */
  mqtt_topic: string;
  /** AI provider identifier (e.g. "gemini", "openai", "ollama", "none"). */
  ai_provider: string;
  /** AI model identifier (e.g. "gemini-2.5-flash"). */
  ai_model: string;
  /** AI API key (empty string for local providers). */
  ai_api_key: string;
  /** TTS engine identifier (e.g. "piper", "kokoro", "elevenlabs"). */
  tts_engine: string;
  /** TTS voice identifier for the selected engine. */
  tts_voice: string;
  /** API key for cloud TTS engines (empty string for local engines). */
  tts_api_key: string;
  /** Host URL for self-hosted TTS engines like Kokoro (empty string when not used). */
  tts_host: string;
  /** Response mode name (e.g. "live_operator", "police_dispatch"). */
  response_mode: string;
  /**
   * Camera configuration map.
   * Key is the Frigate camera name.
   */
  cameras: Record<string, { enabled: boolean; go2rtc_stream: string; audio_codec?: string }>;
}

/** Response from POST /api/setup/generate. */
export interface GenerateConfigResult {
  /** Whether the config was written successfully. */
  success: boolean;
  /** Path where config.yaml was written. */
  config_path: string;
  /** Human-readable status message. */
  message: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Check whether a config.yaml exists and retrieve any env-based hints.
 *
 * Called on every app load by SetupGuard to decide whether to show the wizard.
 *
 * @returns SetupStatus with config_exists and frigate_host_env fields
 */
export async function getSetupStatus(): Promise<SetupStatus> {
  const response = await apiClient.get<SetupStatus>('/setup/status');
  return response.data;
}

/**
 * Probe Frigate, go2rtc, and MQTT to discover what is available.
 *
 * The backend attempts connections in parallel and returns a full ProbeResult
 * regardless of which services succeeded or failed.
 *
 * @param req - Probe request with at minimum a frigate_host
 * @returns ProbeResult with per-service reachability and camera lists
 */
export async function probeServices(req: ProbeRequest): Promise<ProbeResult> {
  const response = await apiClient.post<ProbeResult>('/setup/probe', req, {
    // Probe can take a few seconds if services are slow
    timeout: 20_000,
  });
  return response.data;
}

/**
 * Generate config.yaml from the wizard-collected settings and start VoxWatch.
 *
 * On success the backend writes config.yaml and signals the service to load it.
 * The frontend should then navigate to '/' after a short countdown.
 *
 * @param req - Complete setup configuration collected across all wizard steps
 * @returns GenerateConfigResult indicating success and the written config path
 */
export async function generateConfig(req: GenerateConfigRequest): Promise<GenerateConfigResult> {
  const response = await apiClient.post<GenerateConfigResult>('/setup/generate', req, {
    // Config generation can take a moment if TTS caches need to be built
    timeout: 30_000,
  });
  return response.data;
}
