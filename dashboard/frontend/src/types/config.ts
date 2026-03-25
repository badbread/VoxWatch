/**
 * TypeScript type definitions for the VoxWatch configuration schema.
 *
 * Every interface here mirrors a top-level section (or nested sub-section) in
 * config.yaml so the frontend config editor can validate, display, and submit
 * changes with full type safety. When the YAML schema changes, update these
 * interfaces to match.
 */

/** Frigate NVR connection settings. */
export interface FrigateConfig {
  /** Frigate hostname or IP address. */
  host: string;
  /** Frigate HTTP API port (default 5000). */
  port: number;
  /** MQTT broker hostname. */
  mqtt_host: string;
  /** MQTT broker port (default 1883). */
  mqtt_port: number;
  /** Frigate MQTT event topic (default "frigate/events"). */
  mqtt_topic: string;
  /** Optional MQTT username. */
  mqtt_user?: string;
  /** Optional MQTT password. */
  mqtt_password?: string;
}

/** go2rtc reverse-proxy / media server connection settings. */
export interface Go2rtcConfig {
  /** go2rtc hostname or IP address. */
  host: string;
  /** go2rtc HTTP API port (default 1984). */
  api_port: number;
}

/** Per-camera configuration entry. Keys are Frigate camera names. */
export interface CameraConfig {
  /** Whether this camera should participate in deterrent triggers. */
  enabled: boolean;
  /** Stream name in the go2rtc configuration (used for audio push). */
  go2rtc_stream: string;
  /** Scene context describing the camera's field of view for AI spatial awareness. */
  scene_context?: string;
  /**
   * Per-camera audio codec override. When set, this value takes precedence over
   * the global `audio.codec` setting for this specific camera's backchannel push.
   * Use the FFmpeg codec name (e.g. "pcm_mulaw" for Reolink, "pcm_alaw" for Dahua).
   * Leave undefined to inherit the global default.
   */
  audio_codec?: string | undefined;
  /**
   * Per-camera sample rate override in Hz.
   * Leave undefined to inherit the global `audio.sample_rate` value.
   */
  sample_rate?: number | undefined;
  /**
   * Per-camera channel count override (1 = mono, 2 = stereo).
   * Leave undefined to inherit the global `audio.channels` value.
   */
  channels?: number | undefined;
}

/** Active-hours window definition. */
export interface ActiveHoursConfig {
  /**
   * Operating mode:
   * - "always"           — deterrent is active 24/7
   * - "sunset_sunrise"   — active between sunset and sunrise (requires lat/lng)
   * - "fixed"            — active between start and end time strings
   */
  mode: 'always' | 'sunset_sunrise' | 'fixed';
  /** HH:MM start time (only used when mode is "fixed"). */
  start: string;
  /** HH:MM end time (only used when mode is "fixed"). */
  end: string;
}

/** Detection trigger conditions. */
export interface ConditionsConfig {
  /** Minimum Frigate detection confidence score (0.0–1.0). */
  min_score: number;
  /** Per-camera cooldown between triggers, in seconds. */
  cooldown_seconds: number;
  /** Active-hours configuration. */
  active_hours: ActiveHoursConfig;
  /** Latitude for sunset/sunrise calculations. */
  latitude: number;
  /** Longitude for sunset/sunrise calculations. */
  longitude: number;
}

/**
 * Unified AI vision provider configuration — used for both primary and fallback.
 *
 * `api_key` and `host` are both optional so that any provider type can be
 * assigned to either slot without schema mismatches:
 *   - Cloud providers (gemini, openai, anthropic, grok): set api_key, leave host undefined
 *   - Self-hosted providers (ollama):                    set host, leave api_key undefined
 *   - Custom OpenAI-compatible endpoints:                may set both
 */
export interface AiProviderConfig {
  /** Provider identifier string (e.g. "gemini", "openai", "ollama", "custom"). */
  provider: string;
  /** Model name or tag (e.g. "gemini-2.5-flash", "llava:7b"). */
  model: string;
  /** API key for cloud providers. Use ${ENV_VAR} syntax to avoid committing secrets. */
  api_key?: string;
  /** Base URL for self-hosted providers (e.g. "http://localhost:11434" for Ollama). */
  host?: string;
  /** Per-request timeout in seconds (1–120). */
  timeout_seconds: number;
}

/** AI vision configuration — primary provider with fallback. */
export interface AiConfig {
  primary: AiProviderConfig;
  fallback: AiProviderConfig;
}

/** Stage 2 — multi-snapshot AI analysis settings (legacy compat). */
export interface Stage2Config {
  snapshot_count: number;
  snapshot_interval_ms: number;
}

/** Stage 3 — video-clip behavioral analysis settings (legacy compat). */
export interface Stage3Config {
  enabled: boolean;
  video_clip_seconds: number;
  person_still_present_check: boolean;
  fallback_to_snapshots: boolean;
  fallback_snapshot_count: number;
}

/**
 * @deprecated Legacy stage type identifiers — kept for backward compatibility
 * with older config.yaml files that still use the `pipeline.stages[]` array format.
 * The new pipeline uses the flat `initial_response / escalation / resolution` keys.
 */
export type PipelineStageType = 'pre_stage' | 'ai_snapshot' | 'ai_video' | 'all_clear';

/**
 * @deprecated Legacy stage shape — kept so older configs can still be read.
 * New code should use PipelineInitialResponse, PipelineEscalation, PipelineResolution.
 */
export interface PipelineStage {
  type: PipelineStageType;
  enabled: boolean;
  order: number;
  message?: string;
  prefix?: string;
  suffix?: string;
  snapshot_count?: number;
  snapshot_interval_ms?: number;
  video_clip_seconds?: number;
  check_person_present?: boolean;
  fallback_to_snapshots?: boolean;
  fallback_snapshot_count?: number;
  attention_tone?: string;
  attention_tone_custom_path?: string;
}

/**
 * Initial Response stage — plays immediately on detection with no AI required.
 * Uses the response mode's pre-cached default message unless overridden.
 */
export interface PipelineInitialResponse {
  /** Whether this stage is active (default true). */
  enabled: boolean;
  /** Delay in seconds before playing (default 0). */
  delay: number;
  /**
   * Optional message override. When omitted the backend uses the response
   * mode's built-in DEFAULT_MESSAGES entry.
   */
  message?: string;
  /** Attention tone for this stage. */
  attention_tone?: string;
  /** Custom WAV path — only used when attention_tone is "custom". */
  attention_tone_custom_path?: string;
}

/**
 * Escalation stage — AI-powered response. Fires after `delay` seconds if
 * the person is still present after the Initial Response.
 */
export interface PipelineEscalation {
  /** Whether this stage is active (default true). */
  enabled: boolean;
  /** Delay in seconds after Initial Response (default 6). */
  delay: number;
  /**
   * Firing condition:
   *   "person_still_present" — only fires if Frigate still reports a person.
   *   "always"               — fires unconditionally after the delay.
   */
  condition: 'person_still_present' | 'always';
  /** Attention tone for this stage. */
  attention_tone?: string;
  /** Custom WAV path — only used when attention_tone is "custom". */
  attention_tone_custom_path?: string;
}

/**
 * Resolution stage — optional message when the person leaves.
 * Plays after the last active stage. Disabled by default.
 */
export interface PipelineResolution {
  /** Whether this stage is active (default false). */
  enabled: boolean;
  /** Message to play when the area is clear (default "Area clear."). */
  message: string;
  /** Attention tone for this stage. */
  attention_tone?: string;
  /** Custom WAV path — only used when attention_tone is "custom". */
  attention_tone_custom_path?: string;
}

/**
 * Pipeline configuration — flat stage definitions matching the backend's
 * `pipeline.initial_response / escalation / resolution` structure.
 *
 * The legacy `stages` array is kept optional so existing config.yaml files
 * that still use the old format can be loaded without errors.
 */
export interface PipelineConfig {
  /** Initial Response stage settings. */
  initial_response?: PipelineInitialResponse;
  /** Escalation stage settings. */
  escalation?: PipelineEscalation;
  /** Resolution stage settings. */
  resolution?: PipelineResolution;
  /**
   * @deprecated Legacy ordered-stages array. Kept for backward compatibility.
   * New code ignores this field; the backend reads initial_response/escalation/resolution.
   */
  stages?: PipelineStage[];
}

/** Text-to-Speech engine settings. */
export interface TtsConfig {
  /**
   * TTS backend identifier. One of:
   *   "kokoro" | "piper" | "elevenlabs" | "cartesia" | "polly" | "openai" | "espeak"
   */
  engine: string;

  // ---- Kokoro (neural, local or remote) ------------------------------------
  /** Kokoro HTTP host URL (e.g. "http://kokoro-server:8880"). */
  kokoro_host?: string;
  /** Kokoro voice ID (e.g. "af_heart"). */
  kokoro_voice?: string;
  /** Kokoro generation speed multiplier (0.5 – 2.0). */
  kokoro_speed?: number;

  // ---- Piper (local neural TTS) --------------------------------------------
  /** Piper voice model name (e.g. "en_US-lessac-medium"). */
  piper_model: string;
  /** Piper generation speed multiplier (0.5 – 2.0). */
  voice_speed: number;

  // ---- ElevenLabs (premium cloud) -----------------------------------------
  /** ElevenLabs API key. */
  elevenlabs_api_key?: string;
  /** ElevenLabs voice ID (UUID string from ElevenLabs voice library). */
  elevenlabs_voice_id?: string;
  /** ElevenLabs model ID (e.g. "eleven_flash_v2_5"). */
  elevenlabs_model?: string;
  /** ElevenLabs voice stability (0.0 – 1.0). Higher = more consistent. */
  elevenlabs_stability?: number;
  /** ElevenLabs similarity boost (0.0 – 1.0). Higher = closer to original voice. */
  elevenlabs_similarity?: number;

  // ---- Cartesia (low-latency cloud) ----------------------------------------
  /** Cartesia API key. */
  cartesia_api_key?: string;
  /** Cartesia voice ID (UUID). */
  cartesia_voice_id?: string;
  /** Cartesia model ID (e.g. "sonic-2"). */
  cartesia_model?: string;
  /** Cartesia playback speed multiplier (0.5 – 2.0). */
  cartesia_speed?: number;

  // ---- Amazon Polly (budget cloud) ----------------------------------------
  /** AWS region for Polly (e.g. "us-east-1"). */
  polly_region?: string;
  /** Polly voice ID (e.g. "Matthew", "Joanna"). */
  polly_voice_id?: string;
  /** Polly synthesis engine: "neural" or "generative". */
  polly_engine?: string;

  // ---- OpenAI TTS (cloud) -------------------------------------------------
  /** OpenAI API key. */
  openai_api_key?: string;
  /** OpenAI TTS model (e.g. "tts-1", "tts-1-hd"). */
  openai_model?: string;
  /** OpenAI voice name (e.g. "alloy", "echo"). */
  openai_voice?: string;
  /** OpenAI playback speed multiplier (0.25 – 4.0). */
  openai_speed?: number;

  // ---- eSpeak (robotic fallback, always available) -------------------------
  /** eSpeak speech rate in words-per-minute (80 – 450). */
  espeak_speed?: number;
  /** eSpeak pitch (0 – 99). */
  espeak_pitch?: number;
}

/** Audio encoding settings for camera backchannel compatibility. */
export interface AudioConfig {
  /** FFmpeg codec name (e.g. "pcm_mulaw" for G.711 μ-law). */
  codec: string;
  /** Sample rate in Hz (e.g. 8000 for G.711). */
  sample_rate: number;
  /** Number of audio channels (typically 1 for voice). */
  channels: number;
}

/** Audio push HTTP server settings. */
export interface AudioPushConfig {
  /** Port for the temporary HTTP server that serves audio files to go2rtc. */
  serve_port: number;
}

/** Pre-cached deterrent message templates. */
export interface MessagesConfig {
  /** Stage 1 static warning message. */
  stage1: string;
  /** Stage 2 spoken prefix before the AI-generated description. */
  stage2_prefix: string;
  /** Stage 2 spoken suffix after the AI-generated description. */
  stage2_suffix: string;
  /** Stage 3 spoken prefix before the AI behavioral analysis. */
  stage3_prefix: string;
  /** Stage 3 spoken suffix after the AI behavioral analysis. */
  stage3_suffix: string;
  /** Attention tone for Stage 1: "none", "short", "long", "siren", or custom WAV path. */
  stage1_tone?: string;
  /** Attention tone for Stage 2. */
  stage2_tone?: string;
  /** Attention tone for Stage 3. */
  stage3_tone?: string;
  /** Custom WAV file path for Stage 1 (replaces TTS if set). */
  stage1_custom_audio?: string;
  /** Custom WAV file path for Stage 2 (replaces TTS if set). */
  stage2_custom_audio?: string;
  /** Custom WAV file path for Stage 3 (replaces TTS if set). */
  stage3_custom_audio?: string;
}

/**
 * Dispatch-specific customization fields.
 *
 * Stored under `response_mode.dispatch` in config.yaml. All fields are
 * optional — the dispatch pipeline degrades gracefully when they are absent,
 * using generic fallback phrasing ("the property", no callsign, etc.).
 */
export interface DispatchConfig {
  /**
   * Street address of the monitored property.
   * Used in callouts: "10-97 at {address}."
   */
  address?: string;
  /** City name appended to address in longer callouts. */
  city?: string;
  /** Two-letter state abbreviation (e.g. "CA"). */
  state?: string;
  /**
   * Computed full address string ("123 Main St, Springfield, CA").
   * Derived from address + city + state by the frontend before saving.
   */
  full_address?: string;
  /**
   * Optional responding agency name (e.g. "County Sheriff").
   * Adds realism: "County Sheriff dispatch, 10-97 at..."
   */
  agency?: string;
  /**
   * Optional unit callsign (e.g. "Unit 7").
   * When set: "Unit 7, respond code 3."
   */
  callsign?: string;
  /**
   * Whether to include the address in spoken dispatch messages.
   * When false, generic phrasing ("the property") is used instead.
   * Defaults to true.
   */
  include_address?: boolean;
  /** Enable officer acknowledgment after dispatch call. Default true. */
  officer_response?: boolean;
  /** Officer's unit callsign (e.g. "Unit 7"). Falls back to dispatch callsign. */
  officer_callsign?: string;
  /** Kokoro voice for the dispatcher (female). Default "af_bella". */
  dispatcher_voice?: string;
  /** ElevenLabs voice ID for the dispatcher. Leave blank to use the global ElevenLabs voice. */
  dispatcher_elevenlabs_voice?: string;
  /** OpenAI TTS voice for the dispatcher. Default "nova". */
  dispatcher_openai_voice?: string;
  /** Kokoro voice for the officer (deep male). Default "am_fenrir". */
  officer_voice?: string;
  /** ElevenLabs voice ID for the officer (male). Leave blank to use the global ElevenLabs voice. */
  officer_elevenlabs_voice?: string;
  /** OpenAI TTS voice for the officer (male). Default "onyx". */
  officer_openai_voice?: string;
  /** Enable "Connecting to dispatch frequency..." intro with tuning static. Default true. */
  channel_intro?: boolean;
  /**
   * Absolute path to a custom intro audio file (WAV or MP3).
   * When set and the file exists, it is used directly as the channel intro —
   * no TTS or chatter generation occurs. Leave empty to use auto-generation.
   * Priority: custom file > cached generated (/data/audio/dispatch_intro_cached.wav) > auto.
   * Example: "/config/audio/dispatch_intro.wav"
   */
  intro_audio?: string;
  /**
   * Template text for the auto-generated intro voice line.
   * Supports {agency} substitution from the agency field above.
   * Only used when intro_audio is empty and no cached intro exists.
   * Default: "Connecting to {agency} dispatch frequency."
   */
  intro_text?: string;
}

/**
 * Response mode configuration — controls the speaking style of deterrent messages.
 *
 * The response mode modifier is prepended to the Stage 2 and Stage 3 AI prompts
 * so the generated descriptions adopt a specific character voice.
 *
 * Built-in mode names: police_dispatch, live_operator, private_security,
 * recorded_evidence, homeowner, automated_surveillance, guard_dog,
 * neighborhood_watch, mafioso, tony_montana, pirate_captain, british_butler,
 * disappointed_parent, custom.
 * When name is "custom", custom_prompt is used as the modifier instead.
 */
export interface ResponseModeConfig {
  /**
   * Response mode name. One of the built-in names or "custom".
   * When "custom", custom_prompt is used as the AI modifier.
   */
  name: string;
  /**
   * Custom response mode prompt override — only used when name is "custom".
   * Instruct the AI on who to be, what tone to use, and how to address
   * the detected person. Keep under 200 words for best results.
   */
  custom_prompt?: string | undefined;
  /**
   * Dispatch-specific customization fields.
   * Only consumed by dispatch-mode response modes (e.g. police_dispatch).
   * Safe to include in the config regardless of active mode — non-dispatch
   * modes ignore it entirely.
   */
  dispatch?: DispatchConfig;
}

/**
 * @deprecated Use ResponseModeConfig instead. Kept for backward compatibility
 * during migration from the "persona" config key to "response_mode".
 */
export type PersonaConfig = ResponseModeConfig;

/** Logging configuration. */
export interface LoggingConfig {
  /** Log level: "DEBUG" | "INFO" | "WARNING" | "ERROR". */
  level: string;
  /** Absolute path to the log file on the container filesystem. */
  file: string;
}

/**
 * Root VoxWatch configuration object — aggregates all section interfaces.
 * This shape is serialized to / deserialized from config.yaml by the backend.
 */
export interface VoxWatchConfig {
  frigate: FrigateConfig;
  go2rtc: Go2rtcConfig;
  /** Map of Frigate camera name → camera config. */
  cameras: Record<string, CameraConfig>;
  conditions: ConditionsConfig;
  ai: AiConfig;
  stage2: Stage2Config;
  stage3: Stage3Config;
  pipeline?: PipelineConfig;
  tts: TtsConfig;
  audio: AudioConfig;
  audio_push: AudioPushConfig;
  messages: MessagesConfig;
  /** Response mode — controls the speaking style of deterrent messages. */
  response_mode: ResponseModeConfig;
  /**
   * @deprecated Use response_mode instead. Kept for backward-compat with
   * older config.yaml files that still use the "persona" key.
   */
  persona?: PersonaConfig;
  logging: LoggingConfig;
}

/** Validation result returned by the backend or client-side validator. */
export interface ConfigValidationResult {
  valid: boolean;
  errors: ConfigValidationError[];
}

/** A single validation error pointing to a field path. */
export interface ConfigValidationError {
  /** Dot-separated path to the invalid field (e.g. "conditions.min_score"). */
  field: string;
  /** Human-readable error message. */
  message: string;
}
