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

/**
 * Per-camera detection schedule.
 *
 * When present on a camera config, this schedule takes priority over the
 * global `conditions.active_hours` setting for that camera only.
 * Omit (or set to undefined) to use the global schedule.
 */
export interface CameraSchedule {
  /**
   * Schedule mode:
   *   "always"          — camera is active 24/7 regardless of global schedule
   *   "scheduled"       — active within a fixed start/end time window
   *   "sunset_sunrise"  — active from sunset to sunrise (with optional offsets)
   */
  mode: 'always' | 'scheduled' | 'sunset_sunrise';
  /** Start time in HH:MM 24-hour format (used when mode is "scheduled"). */
  start?: string;
  /** End time in HH:MM 24-hour format (used when mode is "scheduled"). */
  end?: string;
  /**
   * Minutes offset applied to sunset. Negative = window starts before sunset.
   * Only used when mode is "sunset_sunrise".
   */
  sunset_offset_minutes?: number;
  /**
   * Minutes offset applied to sunrise. Positive = window ends after sunrise.
   * Only used when mode is "sunset_sunrise".
   */
  sunrise_offset_minutes?: number;
}

/** Per-camera configuration entry. Keys are Frigate camera names. */
export interface CameraConfig {
  /** Whether this camera should participate in deterrent triggers. */
  enabled: boolean;
  /** Stream name in the go2rtc configuration (used for audio push). */
  go2rtc_stream: string;
  /**
   * Override which camera speaker plays audio when this camera detects someone.
   * Set to another camera's go2rtc stream name to route audio to a different speaker.
   * When empty or undefined, audio plays through this camera's own speaker.
   */
  audio_output?: string;
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
  /**
   * Per-camera detection schedule.
   * When set, this overrides the global `conditions.active_hours` for this
   * camera only. Omit or leave undefined to use the global schedule.
   */
  schedule?: CameraSchedule;
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
  /**
   * City name for sunset/sunrise lookup (e.g. "San Francisco").
   * Takes precedence over latitude/longitude when set.
   * Leave empty to use explicit lat/lon instead.
   */
  city?: string;
  /** Latitude for sunset/sunrise calculations. */
  latitude: number;
  /** Longitude for sunset/sunrise calculations. */
  longitude: number;
  /**
   * Global minutes offset applied to sunset.
   * Negative = window starts before sunset.
   * Applied when active_hours.mode is "sunset_sunrise".
   */
  sunset_offset_minutes?: number;
  /**
   * Global minutes offset applied to sunrise.
   * Positive = window ends after sunrise.
   * Applied when active_hours.mode is "sunset_sunrise".
   */
  sunrise_offset_minutes?: number;
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
/** Persistent Deterrence (Stage 3) — loops after escalation if person stays. */
export interface PipelinePersistentDeterrence {
  enabled: boolean;
  delay_seconds: number;
  max_iterations: number;
  alarm_tone: 'none' | 'brief' | 'continuous';
  describe_actions: boolean;
  escalation_tone: 'steady' | 'increasing';
}

export interface PipelineConfig {
  /** Initial Response stage settings. */
  initial_response?: PipelineInitialResponse;
  /** Escalation stage settings. */
  escalation?: PipelineEscalation;
  /** Persistent Deterrence — loops if person stays after escalation. */
  persistent_deterrence?: PipelinePersistentDeterrence;
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
 * neighborhood_watch, custom.
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
   * Mood/attitude modifier for persona modes that support it (e.g. homeowner).
   * Changes the tone and intensity of the AI-generated messages without
   * changing the persona itself. One of: "observant", "friendly", "firm",
   * "confrontational", "threatening". Defaults to "firm" if not set.
   */
  mood?: string;
  /**
   * Dispatch-specific customization fields.
   * Only consumed by dispatch-mode response modes (e.g. police_dispatch).
   * Safe to include in the config regardless of active mode — non-dispatch
   * modes ignore it entirely.
   */
  dispatch?: DispatchConfig;
  /** Surveillance preset for automated_surveillance mode. */
  surveillance_preset?: string;
  /** Custom system name for automated_surveillance mode. */
  system_name?: string;
  /** Operator name for live_operator mode. */
  operator_name?: string;
  /** Guard dog customization settings. */
  guard_dog?: {
    /** Dog names (0-3). Empty array = generic "the dogs". */
    dog_names?: string[];
  };
  /** Per-persona voice overrides. Keys are mode IDs. */
  voice_overrides?: Record<string, ModeVoiceConfig>;
}

/**
 * @deprecated Use ResponseModeConfig instead. Kept for backward compatibility
 * during migration from the "persona" config key to "response_mode".
 */
export type PersonaConfig = ResponseModeConfig;

// ---------------------------------------------------------------------------
// New structured mode system (v0.3+)
// ---------------------------------------------------------------------------

/** Audio/TTS mood and processing hints for a response mode. */
export interface ModeToneConfig {
  /** High-level mood string passed to expressive TTS providers (e.g. "authoritative"). */
  mood?: string;
  /** Playback speed relative to 1.0 (0.5–2.0). Values below 1.0 slow speech down. */
  speed_multiplier?: number;
  /** Whether to apply the radio bandpass/static effect for this mode. */
  radio_effect?: boolean;
}

/** Optional per-mode TTS voice overrides. Absent fields inherit global TTS config. */
export interface ModeVoiceConfig {
  /** Kokoro voice ID override for this mode (e.g. "af_bella"). */
  kokoro_voice?: string;
  /** OpenAI TTS voice name override (e.g. "nova", "onyx"). */
  openai_voice?: string;
  /** ElevenLabs voice ID (UUID string) override. */
  elevenlabs_voice?: string;
  /** Piper model name override (e.g. "en_US-lessac-medium"). */
  piper_model?: string;
}

/** Runtime behavioral flags that alter how the pipeline handles a mode. */
export interface ModeBehaviorConfig {
  /** When true, route audio through the segmented radio-dispatch pipeline. */
  is_dispatch?: boolean;
  /** When true, apply radio bandpass/static effect to all TTS for this mode. */
  use_radio_effect?: boolean;
  /** When true (dispatch only), append male-voice officer acknowledgment. */
  officer_response?: boolean;
  /** When true, AI prompts request JSON output rather than free text. */
  json_ai_output?: boolean;
  /** When true, prepend scene context to the AI prompt for this mode. */
  scene_context_prefix?: boolean;
}

/** Configuration for a single stage within a response mode. */
export interface ModeStageConfig {
  /**
   * System instruction prepended to the AI prompt for this stage.
   * Empty string means no modification — base prompt runs unaltered.
   */
  prompt_modifier?: string;
  /**
   * Ordered list of fallback phrase strings used when AI fails.
   * Support {variable} substitution (see AI description variables in loader.py).
   * First entry is primary; subsequent entries are alternates.
   */
  templates?: string[];
}

/**
 * A fully-defined VoxWatch response mode.
 *
 * Users can define custom modes under `response_modes.modes` in config.yaml.
 * Built-in modes are always available as a fallback library.
 *
 * AI description variables available in templates and prompt_modifier:
 *   {clothing_description}   — from AI vision
 *   {location_on_property}   — from AI vision
 *   {behavior_description}   — from AI vision
 *   {suspect_count}          — from AI vision
 *   {address_street}         — from config property.street
 *   {address_full}           — from config property.full_address
 *   {time_of_day}            — current time label (morning/evening/night)
 *   {camera_name}            — Frigate camera name from the detection event
 */
export interface ResponseModeDefinition {
  /**
   * Unique mode identifier (e.g. "police_dispatch").
   * Must be lowercase and underscore-separated. Required.
   */
  id: string;
  /**
   * Category grouping: "core" | "advanced" | "novelty" | "custom".
   * Defaults to "custom" for user-defined modes.
   */
  category?: 'core' | 'advanced' | 'novelty' | 'custom';
  /** Human-readable display name shown in the dashboard UI. */
  name?: string;
  /** One-line description of what this mode does and when to use it. */
  description?: string;
  /** Short phrase describing the psychological effect on an intruder. */
  effect?: string;
  /** Audio and TTS mood hints. */
  tone?: ModeToneConfig;
  /** Optional TTS voice overrides (absent = inherit global TTS settings). */
  voice?: ModeVoiceConfig;
  /** Runtime pipeline behavior flags. */
  behavior?: ModeBehaviorConfig;
  /**
   * Stage definitions keyed by "stage1", "stage2", "stage3".
   * Missing stage keys fall back to an empty StageConfig (no modifier, no templates).
   */
  stages?: {
    stage1?: ModeStageConfig;
    stage2?: ModeStageConfig;
    stage3?: ModeStageConfig;
  };
}

/**
 * The new structured `response_modes` top-level config section.
 *
 * Replaces the flat `response_mode.name` single-mode approach with:
 * - A global active mode
 * - Per-camera overrides
 * - User-defined custom mode library
 */
export interface ResponseModesConfig {
  /**
   * Default mode ID applied to all cameras.
   * Falls back to the legacy `response_mode.name` if absent.
   */
  active_mode?: string;
  /**
   * Per-camera mode override map.
   * Key: Frigate camera name. Value: mode ID.
   * Example: { "backyard_cam": "homeowner", "front_door": "police_dispatch" }
   */
  camera_overrides?: Record<string, string>;
  /**
   * User-defined custom mode definitions.
   * Each entry can override a built-in mode (same `id`) or add new ones.
   */
  modes?: ResponseModeDefinition[];
}

/** MQTT event publishing configuration for Home Assistant integration. */
export interface MqttPublishConfig {
  /** Whether VoxWatch publishes events to MQTT. Default true. */
  enabled?: boolean;
  /** MQTT topic prefix for all VoxWatch events. Default "voxwatch". */
  topic_prefix?: string;
  /** Include AI analysis details in stage events. Default true. */
  include_ai_analysis?: boolean;
  /** Include Frigate snapshot URL in detection events. Default true. */
  include_snapshot_url?: boolean;
}

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
  /**
   * Structured mode system (v0.3+).
   * When present, `active_mode` and `camera_overrides` take precedence over
   * the legacy `response_mode.name` single-key approach.
   */
  response_modes?: ResponseModesConfig;
  /** Response mode — controls the speaking style of deterrent messages. */
  response_mode: ResponseModeConfig;
  /**
   * @deprecated Use response_mode instead. Kept for backward-compat with
   * older config.yaml files that still use the "persona" key.
   */
  persona?: PersonaConfig;
  logging: LoggingConfig;
  /** MQTT event publishing configuration for Home Assistant automations. */
  mqtt_publish?: MqttPublishConfig;
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
