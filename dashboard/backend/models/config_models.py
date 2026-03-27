"""
config_models.py — Pydantic Models for VoxWatch Configuration

Mirrors the complete config.yaml structure so the dashboard can validate,
read, and write configuration through a typed interface.

Design notes:
  - All fields have defaults matching the values in voxwatch/config.py so a
    minimal config.yaml (frigate + go2rtc + cameras only) still parses.
  - Sensitive fields (api_key, mqtt_password) are typed as str but the
    config_service masks them before sending to the browser.
  - ${ENV_VAR} tokens are intentionally preserved as literal strings — the
    dashboard shows and saves them as-is; the VoxWatch service resolves them
    at runtime.
  - Pydantic v2 model_config is used throughout (no deprecated v1 class Meta).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── Frigate Section ───────────────────────────────────────────────────────────

class FrigateConfig(BaseModel):
    """Connection settings for the Frigate NVR API and its MQTT broker."""

    host: str = Field(default="localhost", description="Frigate hostname or IP address")
    port: int = Field(default=5000, ge=1, le=65535, description="Frigate HTTP API port")
    mqtt_host: str = Field(default="localhost", description="MQTT broker hostname or IP")
    mqtt_port: int = Field(default=1883, ge=1, le=65535, description="MQTT broker port")
    mqtt_topic: str = Field(
        default="frigate/events",
        description="MQTT topic Frigate publishes detection events to",
    )
    mqtt_user: str = Field(default="", description="MQTT username (leave blank if not required)")
    mqtt_password: str = Field(
        default="",
        description="MQTT password — stored as ${ENV_VAR} token recommended",
    )


# ── go2rtc Section ────────────────────────────────────────────────────────────

class Go2rtcConfig(BaseModel):
    """Connection settings for the go2rtc audio/video relay."""

    host: str = Field(default="localhost", description="go2rtc hostname or IP address")
    api_port: int = Field(default=1984, ge=1, le=65535, description="go2rtc HTTP API port")


# ── Camera Section ────────────────────────────────────────────────────────────

class CameraConfig(BaseModel):
    """Per-camera configuration block.

    Camera names are the keys in the cameras dict (e.g. 'frontdoor') and
    must match exactly the Frigate camera name and go2rtc stream name.

    The optional audio_codec / sample_rate / channels fields let individual
    cameras override the global audio section. This is necessary when a
    network contains cameras from different vendors that require different
    G.711 variants — for example Reolink uses pcm_mulaw (mu-law) and Dahua
    uses pcm_alaw (A-law).  When these fields are None the global values
    from the audio section are used instead.
    """

    enabled: bool = Field(default=True, description="Whether VoxWatch monitors this camera")
    go2rtc_stream: str = Field(
        default="",
        description="Stream name in go2rtc config — used for audio push target",
    )
    scene_context: str = Field(
        default="",
        description=(
            "Optional description of the camera's field of view so the AI can "
            "reference landmarks. Example: 'The front door is on the left. "
            "The driveway is in the center. The kitchen window is on the right.'"
        ),
    )
    audio_codec: Optional[str] = Field(
        default=None,
        description=(
            "Per-camera ffmpeg codec override (e.g. 'pcm_mulaw', 'pcm_alaw'). "
            "When set, this takes precedence over the global audio.codec value "
            "for this camera's backchannel push. Leave None to inherit the global setting."
        ),
    )
    sample_rate: Optional[int] = Field(
        default=None,
        ge=8000,
        le=48000,
        description=(
            "Per-camera sample rate override in Hz. "
            "Leave None to inherit the global audio.sample_rate value."
        ),
    )
    channels: Optional[int] = Field(
        default=None,
        ge=1,
        le=2,
        description=(
            "Per-camera channel count override (1 = mono, 2 = stereo). "
            "Leave None to inherit the global audio.channels value."
        ),
    )


# ── Conditions Section ────────────────────────────────────────────────────────

class ActiveHoursConfig(BaseModel):
    """Controls when VoxWatch is allowed to trigger deterrent audio.

    Modes:
      - always:           Active 24/7
      - sunset_sunrise:   Active from sunset to sunrise (requires lat/lon)
      - fixed:            Active within start/end time window
    """

    mode: Literal["always", "sunset_sunrise", "fixed"] = Field(
        default="always",
        description="Scheduling mode — 'always', 'sunset_sunrise', or 'fixed'",
    )
    start: str = Field(
        default="22:00",
        description="Start time for 'fixed' mode (HH:MM, 24-hour)",
        pattern=r"^\d{2}:\d{2}$",
    )
    end: str = Field(
        default="06:00",
        description="End time for 'fixed' mode (HH:MM, 24-hour)",
        pattern=r"^\d{2}:\d{2}$",
    )


class ConditionsConfig(BaseModel):
    """Trigger conditions that must ALL be met before the deterrent fires."""

    min_score: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum Frigate detection confidence score (0.0–1.0)",
    )
    cooldown_seconds: int = Field(
        default=60,
        ge=0,
        description="Per-camera cooldown period in seconds between consecutive triggers",
    )
    active_hours: ActiveHoursConfig = Field(
        default_factory=ActiveHoursConfig,
        description="Time-of-day schedule controlling when VoxWatch is active",
    )
    latitude: float = Field(
        default=37.7749,
        ge=-90.0,
        le=90.0,
        description="Latitude for sunset/sunrise calculation (decimal degrees)",
    )
    longitude: float = Field(
        default=-122.4194,
        ge=-180.0,
        le=180.0,
        description="Longitude for sunset/sunrise calculation (decimal degrees)",
    )


# ── AI Section ────────────────────────────────────────────────────────────────

class AiProviderConfig(BaseModel):
    """Settings for a single AI vision provider — used for both primary and fallback.

    All credential and endpoint fields are optional so that the same model can
    represent cloud providers (which need api_key), self-hosted providers such as
    Ollama (which need host), or future providers that may need both or neither.

    Field presence is driven by the selected provider at runtime:
      - Cloud providers (gemini, openai, anthropic, grok): populate api_key
      - Self-hosted providers (ollama, custom):             populate host
      - Custom OpenAI-compatible endpoints:                 may need both

    Defaults are set to match the canonical primary configuration (Gemini Flash)
    so that a minimal config.yaml with no ai section still produces a usable object.
    """

    provider: str = Field(
        default="gemini",
        description="Provider identifier — e.g. 'gemini', 'openai', 'anthropic', 'ollama', 'custom'",
    )
    model: str = Field(
        default="gemini-2.5-flash",
        description="Model name or identifier (provider-specific string)",
    )
    api_key: Optional[str] = Field(
        default=None,
        description=(
            "API key for cloud providers — use ${ENV_VAR} syntax to avoid committing secrets. "
            "Leave None for self-hosted providers that do not require authentication."
        ),
    )
    host: Optional[str] = Field(
        default=None,
        description=(
            "Base URL for self-hosted providers (e.g. 'http://localhost:11434' for Ollama). "
            "Leave None for cloud providers that use their own SDK endpoints."
        ),
    )
    timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=120,
        description="Per-request timeout in seconds (1–120)",
    )


class AiConfig(BaseModel):
    """AI vision configuration — primary provider with local/cloud fallback.

    Both primary and fallback use the unified AiProviderConfig model so that
    either slot can be assigned any supported provider without schema mismatches.
    """

    primary: AiProviderConfig = Field(
        default_factory=AiProviderConfig,
        description="Primary AI provider (Gemini Flash recommended for speed)",
    )
    fallback: AiProviderConfig = Field(
        default_factory=lambda: AiProviderConfig(
            provider="ollama",
            model="llava:7b",
            host="http://localhost:11434",
            timeout_seconds=8,
        ),
        description="Fallback provider used when primary fails or times out",
    )


# ── Stage Settings ────────────────────────────────────────────────────────────

class Stage2Config(BaseModel):
    """Stage 2 — AI snapshot analysis settings.

    Stage 2 runs concurrently with Stage 1 audio playback. Multiple snapshots
    are captured in quick succession and sent to the AI for a physical description.
    """

    snapshot_count: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of snapshots captured and sent to AI for analysis",
    )
    snapshot_interval_ms: int = Field(
        default=1000,
        ge=100,
        description="Milliseconds between additional snapshot captures",
    )


class Stage3Config(BaseModel):
    """Stage 3 — AI behavioral analysis settings.

    Stage 3 fires only if the person is still detected after Stage 2 audio.
    It uses a short video clip for richer context about the intruder's behavior.
    """

    enabled: bool = Field(
        default=True,
        description="Whether Stage 3 behavioral analysis is active",
    )
    video_clip_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Length of video clip captured for behavioral analysis",
    )
    person_still_present_check: bool = Field(
        default=True,
        description="Only fire Stage 3 if Frigate still shows a person in frame",
    )
    fallback_to_snapshots: bool = Field(
        default=True,
        description="Use snapshots if video clip capture is unavailable",
    )
    fallback_snapshot_count: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of snapshots to use when falling back from video",
    )


# ── TTS Section ───────────────────────────────────────────────────────────────

class TtsConfig(BaseModel):
    """Text-to-speech engine configuration.

    Supports multiple TTS providers: kokoro (recommended), piper, elevenlabs,
    cartesia, polly, openai, espeak. Provider-specific settings use flat
    prefixed keys (e.g. kokoro_host, elevenlabs_api_key).
    """

    model_config = ConfigDict(extra="allow")

    engine: str = Field(
        default="piper",
        description="TTS provider: kokoro, piper, elevenlabs, cartesia, polly, openai, espeak",
    )
    # Piper defaults
    piper_model: str = Field(
        default="en_US-lessac-medium",
        description="Piper voice model name",
    )
    voice_speed: float = Field(
        default=1.0,
        ge=0.25,
        le=4.0,
        description="Speech rate multiplier (1.0 = normal speed)",
    )
    # Kokoro
    kokoro_host: Optional[str] = Field(default=None, description="Kokoro HTTP server URL")
    kokoro_voice: Optional[str] = Field(default="af_heart", description="Kokoro voice ID")
    kokoro_speed: Optional[float] = Field(default=1.0, description="Kokoro speed multiplier")
    # ElevenLabs
    elevenlabs_api_key: Optional[str] = Field(default=None, description="ElevenLabs API key")
    elevenlabs_voice_id: Optional[str] = Field(default=None, description="ElevenLabs voice ID")
    elevenlabs_model: Optional[str] = Field(default="eleven_flash_v2_5", description="ElevenLabs model")
    elevenlabs_stability: Optional[float] = Field(default=0.7, description="ElevenLabs stability")
    elevenlabs_similarity: Optional[float] = Field(default=0.8, description="ElevenLabs similarity boost")
    # Cartesia
    cartesia_api_key: Optional[str] = Field(default=None, description="Cartesia API key")
    cartesia_voice_id: Optional[str] = Field(default=None, description="Cartesia voice ID")
    cartesia_model: Optional[str] = Field(default=None, description="Cartesia model")
    cartesia_speed: Optional[float] = Field(default=1.0, description="Cartesia speed")
    # Polly
    polly_region: Optional[str] = Field(default="us-west-2", description="AWS region")
    polly_voice_id: Optional[str] = Field(default="Matthew", description="Polly voice ID")
    polly_engine: Optional[str] = Field(default="neural", description="Polly engine")
    # OpenAI
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    openai_model: Optional[str] = Field(default="tts-1", description="OpenAI TTS model")
    openai_voice: Optional[str] = Field(default="onyx", description="OpenAI voice")
    openai_speed: Optional[float] = Field(default=1.0, description="OpenAI speed")
    # espeak
    espeak_speed: Optional[int] = Field(default=130, description="espeak WPM")
    espeak_pitch: Optional[int] = Field(default=30, description="espeak pitch")


# ── Audio Section ─────────────────────────────────────────────────────────────

class AudioConfig(BaseModel):
    """Audio output format for camera backchannel compatibility.

    Reolink CX410 (and most Reolink cameras) require PCMU (G.711 mu-law)
    at 8000 Hz mono. Other cameras may use pcm_alaw (G.711 A-law).
    These values are passed directly to ffmpeg during conversion.
    """

    codec: str = Field(
        default="pcm_mulaw",
        description="ffmpeg codec name — 'pcm_mulaw' (G.711 mu-law) or 'pcm_alaw'",
    )
    sample_rate: int = Field(
        default=8000,
        description="Audio sample rate in Hz — 8000 required for most IP cameras",
    )
    channels: int = Field(
        default=1,
        ge=1,
        le=2,
        description="Number of audio channels (1 = mono, required for camera backchannel)",
    )


class AudioPushConfig(BaseModel):
    """Settings for the temporary HTTP server VoxWatch runs for go2rtc audio delivery.

    go2rtc fetches audio files by URL, so VoxWatch spins up a minimal HTTP
    server pointing at its temp directory. The port here must be reachable
    from the go2rtc container/process.
    """

    serve_port: int = Field(
        default=8891,
        ge=1024,
        le=65535,
        description="TCP port for the temporary audio HTTP server",
    )


# ── MQTT Publishing Section ───────────────────────────────────────────────────

class MqttPublishConfig(BaseModel):
    """MQTT event publishing settings for Home Assistant integration.

    When enabled, VoxWatch publishes structured JSON events to MQTT at
    each stage of a detection.  Home Assistant users can build automations
    that react to lights, locks, notifications, and more.
    """

    enabled: bool = Field(
        default=True,
        description="Whether VoxWatch publishes detection events to MQTT.",
    )
    topic_prefix: str = Field(
        default="voxwatch",
        description="MQTT topic prefix for all VoxWatch events (e.g. 'voxwatch').",
    )
    include_ai_analysis: bool = Field(
        default=True,
        description="Include AI analysis details (clothing, location) in stage events.",
    )
    include_snapshot_url: bool = Field(
        default=True,
        description="Include Frigate snapshot URL in detection started events.",
    )


# ── Messages Section ──────────────────────────────────────────────────────────

class MessagesConfig(BaseModel):
    """Pre-configured warning message templates for each deterrent stage.

    Stage 1 is spoken verbatim. Stage 2/3 have prefix/suffix strings with the
    AI-generated description injected between them at runtime.
    """

    stage1: str = Field(
        default=(
            "Attention. You are on private property. "
            "You are being recorded on camera. "
            "The homeowner has been notified."
        ),
        description="Complete Stage 1 generic warning message (spoken immediately on detection)",
    )
    stage2_prefix: str = Field(
        default="Individual detected.",
        description="Spoken before the AI physical description in Stage 2",
    )
    stage2_suffix: str = Field(
        default="You have been identified and recorded. The homeowner has been notified.",
        description="Spoken after the AI physical description in Stage 2",
    )
    stage3_prefix: str = Field(
        default="Warning.",
        description="Spoken before the AI behavioral description in Stage 3",
    )
    stage3_suffix: str = Field(
        default=(
            "All activity has been recorded and transmitted. "
            "Authorities are being contacted."
        ),
        description="Spoken after the AI behavioral description in Stage 3",
    )


# ── Persona / Response Mode Section ──────────────────────────────────────────


class ModeVoiceOverride(BaseModel):
    """Per-provider voice override for a specific persona.

    Used in ``PersonaConfig.voice_overrides`` to let users swap the TTS voice
    for an individual mode without touching the global TTS provider config.
    Keys are provider-specific voice identifiers; ``None`` means "use the
    mode's built-in default" for that provider.
    """

    kokoro_voice: Optional[str] = Field(
        default=None,
        description="Kokoro voice ID override for this persona (e.g. 'af_bella').",
    )
    openai_voice: Optional[str] = Field(
        default=None,
        description="OpenAI TTS voice override for this persona (e.g. 'nova', 'onyx').",
    )
    elevenlabs_voice: Optional[str] = Field(
        default=None,
        description="ElevenLabs voice ID override for this persona.",
    )
    piper_model: Optional[str] = Field(
        default=None,
        description="Piper model override for this persona (e.g. 'en_US-lessac-medium').",
    )


class DispatchConfig(BaseModel):
    """Dispatch-specific customization fields for the police_dispatch response mode.

    Stored under ``response_mode.dispatch`` in config.yaml.  All fields are
    optional — the dispatch pipeline falls back to generic phrasing ("the
    property", no agency prefix, no callsign) when they are absent or empty.

    When ``address``, ``city``, and ``state`` are all set, the service auto-
    assembles ``full_address`` as "address, city, state" (this is done by the
    dashboard frontend before saving).
    """

    address: str = Field(
        default="",
        description="Street address of the monitored property (e.g. '123 Main Street')",
    )
    city: str = Field(
        default="",
        description="City name (e.g. 'Springfield')",
    )
    state: str = Field(
        default="",
        description="Two-letter US state abbreviation (e.g. 'CA')",
    )
    full_address: str = Field(
        default="",
        description=(
            "Pre-assembled full address string used directly in dispatch callouts. "
            "Auto-computed by the dashboard from address + city + state. "
            "Example: '123 Main Street, Springfield, CA'"
        ),
    )
    agency: str = Field(
        default="",
        description=(
            "Responding agency name (e.g. 'County Sheriff'). "
            "Adds realism: 'County Sheriff dispatch, 10-97 at...'"
        ),
    )
    callsign: str = Field(
        default="",
        description=(
            "Unit callsign (e.g. 'Unit 7'). "
            "When set: 'Unit 7, respond code 3.' instead of 'Nearest unit respond code 3.'"
        ),
    )
    include_address: bool = Field(
        default=True,
        description=(
            "When False, spoken messages use 'the property' instead of the "
            "configured address, even if address is filled in."
        ),
    )
    # ── Officer & Voice Settings ──
    officer_response: bool = Field(
        default=True,
        description="Enable officer acknowledgment after dispatch call.",
    )
    officer_callsign: str = Field(
        default="",
        description="Officer unit callsign (e.g. 'Baker Forty-one'). Falls back to callsign if empty.",
    )
    officer_voice: str = Field(
        default="am_fenrir",
        description="Kokoro voice for the officer (deep male).",
    )
    officer_openai_voice: str = Field(
        default="onyx",
        description="OpenAI voice for officer role.",
    )
    officer_elevenlabs_voice: str = Field(
        default="",
        description="ElevenLabs voice ID for officer role.",
    )
    officer_speed: float = Field(
        default=1.0,
        description="Officer voice speed multiplier.",
    )
    dispatcher_voice: str = Field(
        default="af_bella",
        description="Kokoro voice for the dispatcher (measured female).",
    )
    dispatcher_speed: float = Field(
        default=0.9,
        description="Dispatcher voice speed (slightly slower for measured cadence).",
    )
    dispatcher_openai_voice: str = Field(
        default="nova",
        description="OpenAI voice for dispatcher role.",
    )
    dispatcher_elevenlabs_voice: str = Field(
        default="",
        description="ElevenLabs voice ID for dispatcher role.",
    )
    # ── Channel Intro Settings ──
    channel_intro: bool = Field(
        default=True,
        description="Play 'Connecting to dispatch frequency' intro before the call.",
    )
    intro_audio: str = Field(
        default="",
        description="Path to custom intro WAV/MP3. Overrides auto-generated intro.",
    )
    intro_text: str = Field(
        default="Connecting to {agency} dispatch frequency.",
        description="Template text for auto-generated intro. Supports {agency} token.",
    )


class GuardDogConfig(BaseModel):
    """Guard Dog persona customization settings.

    Holds the optional dog names injected into guard_dog mode templates and
    prompt modifiers.  When ``dog_names`` is empty the mode falls back to the
    generic phrase "the dogs" so all template slots remain grammatically valid.
    """

    dog_names: List[str] = Field(
        default_factory=list,
        description=(
            "Dog names for the guard_dog persona (0-3 names). "
            "Empty list means generic 'the dogs'. "
            "Examples: ['Rex', 'Bruno'], ['Bear']."
        ),
    )


class PersonaConfig(BaseModel):
    """AI persona / response mode configuration.

    Controls the speaking style and character of all deterrent messages.
    The persona modifier is prepended to the Stage 2 and Stage 3 AI prompts so
    the generated descriptions adopt a specific character voice rather than the
    default clinical security style.

    This model is used for both the legacy ``persona`` key and the current
    ``response_mode`` key in config.yaml.  The ``dispatch`` sub-object is only
    consumed when ``name`` is a dispatch-mode (e.g. ``"police_dispatch"``).

    Built-in mode names:
      - ``police_dispatch``   — Female dispatcher voice. 10-codes. Radio static.
      - ``live_operator``     — Simulates a real person watching cameras.
      - ``private_security``  — Professional, firm. Default.
      - ``recorded_evidence`` — Cold system-log tone.
      - ``homeowner``         — Personal, calm, direct.
      - ``automated_surveillance`` — Neutral AI voice.
      - ``guard_dog``         — Implies dog threat. Indirect deterrence.
      - ``neighborhood_watch`` — Community awareness pressure.
      - ``mafioso``           — Tough Italian-American wiseguy.
      - ``tony_montana``      — Scarface energy. Dramatic.
      - ``pirate_captain``    — Theatrical, threatening pirate captain.
      - ``british_butler``    — Impeccably polite but passive-aggressive.
      - ``disappointed_parent`` — Guilt-tripping, sighing disappointed parent.
      - ``custom``            — Uses the ``custom_prompt`` field instead of a built-in.
    """

    name: str = Field(
        default="private_security",
        description=(
            "Response mode name. Must be one of the built-in names or 'custom'. "
            "When set to 'custom', the custom_prompt field is used as the modifier."
        ),
    )
    custom_prompt: str = Field(
        default="",
        description=(
            "Custom response mode prompt override. Only used when name is 'custom'. "
            "Instruct the AI on WHO to be, what TONE to use, and how to ADDRESS "
            "the detected person. Keep under 200 words for best results."
        ),
    )
    mood: str = Field(
        default="firm",
        description=(
            "Mood/attitude modifier for modes that support it (e.g. 'homeowner'). "
            "Changes the tone and intensity of AI-generated messages. "
            "One of: 'observant', 'friendly', 'firm', 'confrontational', 'threatening'. "
            "Ignored by modes that do not implement mood variants."
        ),
    )
    system_name: str = Field(
        default="",
        description=(
            "Custom system name for automated_surveillance mode. "
            "Injected into prompts and templates as the system identity. "
            "Empty string means use generic 'Surveillance system'."
        ),
    )
    surveillance_preset: str = Field(
        default="standard",
        description=(
            "Personality preset for automated_surveillance mode. "
            "One of: 'standard', 't800', 'hal', 'wopr', 'glados'. "
            "Each preset changes speech patterns, voice, and tone."
        ),
    )
    operator_name: str = Field(
        default="",
        description=(
            "Operator name for live_operator mode. "
            "When set, the operator introduces themselves by name. "
            "Empty string means generic 'the operator'."
        ),
    )
    dispatch: DispatchConfig = Field(
        default_factory=DispatchConfig,
        description=(
            "Dispatch-specific address, agency, and callsign settings. "
            "Only consumed when name is a dispatch mode (e.g. 'police_dispatch'). "
            "Safe to include regardless of active mode — non-dispatch modes ignore it."
        ),
    )
    guard_dog: GuardDogConfig = Field(
        default_factory=GuardDogConfig,
        description="Guard dog persona customization (dog names).",
    )
    voice_overrides: Optional[Dict[str, ModeVoiceOverride]] = Field(
        default=None,
        description=(
            "Per-persona voice overrides. Keys are mode IDs (e.g. 'mafioso'), "
            "values are partial voice configs that replace the persona's built-in "
            "voice defaults. Only non-null fields within each override are applied."
        ),
    )


# ── Logging Section ───────────────────────────────────────────────────────────

class LoggingConfig(BaseModel):
    """Python logging configuration for the VoxWatch service."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Log level — DEBUG is very verbose, INFO is recommended for production",
    )
    file: str = Field(
        default="/data/voxwatch.log",
        description="Absolute path to the log file (must be writable by the container)",
    )


# ── Root Config ───────────────────────────────────────────────────────────────

class VoxWatchConfig(BaseModel):
    """Root configuration model — mirrors the complete config.yaml structure.

    This is the single source of truth for config validation in the dashboard.
    All sections have defaults so only frigate, go2rtc, and cameras are required
    to produce a valid configuration.
    """

    frigate: FrigateConfig = Field(
        default_factory=FrigateConfig,
        description="Frigate NVR connection and MQTT broker settings",
    )
    go2rtc: Go2rtcConfig = Field(
        default_factory=Go2rtcConfig,
        description="go2rtc connection settings for audio push",
    )
    cameras: Dict[str, CameraConfig] = Field(
        default_factory=dict,
        description="Map of camera name -> camera config (name must match Frigate camera name)",
    )
    conditions: ConditionsConfig = Field(
        default_factory=ConditionsConfig,
        description="Detection trigger conditions",
    )
    ai: AiConfig = Field(
        default_factory=AiConfig,
        description="AI vision provider settings",
    )
    stage2: Stage2Config = Field(
        default_factory=Stage2Config,
        description="Stage 2 snapshot analysis settings",
    )
    stage3: Stage3Config = Field(
        default_factory=Stage3Config,
        description="Stage 3 behavioral analysis settings",
    )
    tts: TtsConfig = Field(
        default_factory=TtsConfig,
        description="Text-to-speech engine settings",
    )
    audio: AudioConfig = Field(
        default_factory=AudioConfig,
        description="Audio output format for camera backchannel",
    )
    audio_push: AudioPushConfig = Field(
        default_factory=AudioPushConfig,
        description="HTTP server settings for go2rtc audio delivery",
    )
    messages: MessagesConfig = Field(
        default_factory=MessagesConfig,
        description="Warning message templates for each deterrent stage",
    )
    response_mode: PersonaConfig = Field(
        default_factory=PersonaConfig,
        description=(
            "Response mode — controls the speaking style and character of deterrent messages. "
            "Replaces the legacy 'persona' key. Includes dispatch sub-config for "
            "police_dispatch mode."
        ),
    )
    persona: Optional[PersonaConfig] = Field(
        default=None,
        description=(
            "Deprecated: legacy persona key kept for backward compatibility with "
            "older config.yaml files. Use response_mode instead. When present and "
            "response_mode is absent, the service copies persona into response_mode."
        ),
    )
    pipeline: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Pipeline stage configuration: initial_response, escalation, resolution. "
            "Stored as a raw dict to preserve flexible sub-keys (attention_tone, etc.)."
        ),
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description="Logging configuration",
    )
    mqtt_publish: Optional[MqttPublishConfig] = Field(
        default=None,
        description=(
            "MQTT event publishing settings for Home Assistant integration. "
            "When present and enabled, VoxWatch publishes structured JSON events "
            "to MQTT at each detection stage. Omit or set enabled: false to disable."
        ),
    )

    @model_validator(mode="after")
    def at_least_one_camera(self) -> "VoxWatchConfig":
        """Ensure at least one camera is defined (required for VoxWatch to function)."""
        if not self.cameras:
            raise ValueError("At least one camera must be configured under 'cameras'")
        return self

    @model_validator(mode="after")
    def at_least_one_enabled_camera(self) -> "VoxWatchConfig":
        """Ensure at least one camera has enabled: true."""
        enabled = [name for name, cam in self.cameras.items() if cam.enabled]
        if not enabled:
            raise ValueError("At least one camera must be enabled")
        return self


# ── Response Helpers ──────────────────────────────────────────────────────────

class ConfigValidationResult(BaseModel):
    """Result of a config validation check — returned by POST /api/config/validate."""

    valid: bool = Field(description="True if the config passes all validation rules")
    errors: list[str] = Field(
        default_factory=list,
        description="List of human-readable validation error messages",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings (e.g. API key looks unresolved)",
    )


