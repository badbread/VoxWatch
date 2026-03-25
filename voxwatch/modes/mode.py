"""
mode.py — ResponseMode dataclass and supporting configuration types.

Defines the strongly-typed data model for a VoxWatch response mode.  Every
mode — whether built-in or user-defined in config.yaml — is parsed into one
of these objects by ``loader.load_modes()``.

The hierarchy is::

    ResponseMode
    ├── ToneConfig      — audio/TTS mood hints
    ├── VoiceConfig     — optional TTS voice overrides per mode
    ├── BehaviorConfig  — runtime behavior flags (dispatch, radio-effect, etc.)
    └── stages: dict[str, StageConfig]
            ├── "stage1"   — Initial Response (instant, no AI)
            ├── "stage2"   — Escalation (AI appearance description)
            └── "stage3"   — Behavioral escalation (AI behavior analysis)
                    └── StageConfig
                            ├── prompt_modifier — prepended to AI system prompt
                            └── templates: list[str] — fallback phrases

Category values::

    "core"      — Serious deterrent modes suitable for real security use.
    "advanced"  — Targeted psychological pressure / implied consequences.
    "novelty"   — Theatrical characters for demos and community sharing.
    "custom"    — User-defined modes from config.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToneConfig:
    """Mood and audio-processing hints for a response mode.

    These values are advisory — TTS providers that support SSML or emotion
    parameters may use them to shape voice output.  Providers that don't
    support these hints silently ignore them.

    Attributes:
        mood: High-level mood string (e.g. "authoritative", "theatrical",
            "cold"). Passed to expressive TTS providers as an emotion hint.
        speed_multiplier: Playback speed relative to 1.0.  Values below 1.0
            slow speech down (useful for authority or ominous modes);
            above 1.0 speeds it up (useful for urgency or comedy).
        radio_effect: When True, the audio processing pipeline applies the
            police-radio bandpass / static effect to TTS output for this mode.
            Has no effect on modes that already render audio differently (e.g.
            dispatch modes that manage their own effects).
    """

    mood: str = "neutral"
    speed_multiplier: float = 1.0
    radio_effect: bool = False


@dataclass
class VoiceConfig:
    """Optional per-mode TTS voice overrides.

    When a field is ``None`` the global TTS voice setting from config.yaml is
    used.  This lets mode authors specify a distinct voice without requiring
    users to change their global TTS configuration.

    Attributes:
        kokoro_voice: Kokoro voice ID (e.g. "af_bella", "am_fenrir").
        openai_voice: OpenAI TTS voice name (e.g. "nova", "onyx").
        elevenlabs_voice: ElevenLabs voice ID (UUID string).
        piper_model: Piper model name (e.g. "en_US-lessac-medium").
    """

    kokoro_voice: Optional[str] = None
    openai_voice: Optional[str] = None
    elevenlabs_voice: Optional[str] = None
    piper_model: Optional[str] = None


@dataclass
class BehaviorConfig:
    """Runtime behavioral flags that alter how the pipeline processes a mode.

    Attributes:
        is_dispatch: When True, the pipeline routes audio through the
            segmented radio-dispatch path in ``radio_dispatch.py`` instead of
            the standard prefix/AI-description/suffix flow.
        use_radio_effect: When True, the radio bandpass-and-static audio
            effect is applied to all TTS output for this mode.
        officer_response: When True (dispatch modes only), a male-voice
            officer acknowledgment clip is appended after the dispatcher
            segments.  Ignored for non-dispatch modes.
        json_ai_output: When True, AI prompts request a JSON object rather
            than a free-text sentence.  The service parses the JSON before
            building the audio message.  Dispatch modes set this True.
        scene_context_prefix: When True, the per-camera scene_context string
            is prepended to the AI prompt as "Scene context: ...".  Should
            be True for virtually every mode.
    """

    is_dispatch: bool = False
    use_radio_effect: bool = False
    officer_response: bool = True
    json_ai_output: bool = False
    scene_context_prefix: bool = True


@dataclass
class StageConfig:
    """Configuration for a single stage within a response mode.

    Each mode defines up to three stages identified by the keys ``"stage1"``,
    ``"stage2"``, and ``"stage3"``.

    Attributes:
        prompt_modifier: System-role instruction prepended to the base AI
            prompt for this stage.  An empty string means no modification —
            the base prompt runs unaltered.
        templates: Ordered list of fallback phrase strings.  Used when the AI
            call fails or is skipped.  Support ``{variable}`` substitution via
            :func:`loader.get_mode_template`.  The first template is the
            primary; subsequent entries are alternate phrasings the service
            may pick from at random to avoid sounding repetitive.
    """

    prompt_modifier: str = ""
    templates: list[str] = field(default_factory=list)


@dataclass
class ResponseMode:
    """A fully-resolved VoxWatch response mode.

    Instances are created by :func:`loader.load_modes` from either built-in
    definitions or user-supplied YAML under ``response_modes.modes``.

    Attributes:
        id: Unique identifier string (e.g. ``"police_dispatch"``).  Must be
            lowercase, underscored, and unique across all loaded modes.
        category: Grouping label.  One of ``"core"``, ``"advanced"``,
            ``"novelty"``, or ``"custom"``.
        name: Human-readable display name (e.g. ``"Police Dispatch"``).
        description: One-line explanation of what this mode does and when to
            use it.  Shown in the dashboard mode-selector UI.
        effect: Short phrase describing the psychological / audio effect on
            an intruder (e.g. ``"Sounds like a real dispatch center"``).
        tone: :class:`ToneConfig` — audio and mood hints.
        voice: :class:`VoiceConfig` — optional TTS voice overrides.
        behavior: :class:`BehaviorConfig` — runtime pipeline flags.
        stages: Mapping of stage key (``"stage1"``, ``"stage2"``,
            ``"stage3"``) to :class:`StageConfig`.  Missing stage keys are
            treated as empty :class:`StageConfig` instances by the loader.
    """

    id: str
    category: str
    name: str
    description: str
    effect: str
    tone: ToneConfig = field(default_factory=ToneConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    stages: dict[str, StageConfig] = field(default_factory=dict)

    def get_stage(self, stage_key: str) -> StageConfig:
        """Return the StageConfig for a given stage key, or an empty default.

        Args:
            stage_key: One of ``"stage1"``, ``"stage2"``, ``"stage3"``.

        Returns:
            The :class:`StageConfig` for that stage, or a default empty
            instance if the key is not defined for this mode.
        """
        return self.stages.get(stage_key, StageConfig())
