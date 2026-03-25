/**
 * PersonaConfigForm — Visual selector for the AI response mode.
 *
 * Response modes change the speaking style of Stage 2 and Stage 3 AI-generated
 * deterrent messages. Instead of the default clinical description, a Police
 * Dispatch mode sounds like a real scanner call, while Italian Mafioso adds
 * some street-level personality.
 *
 * The form renders mode cards organised into three groups:
 *   - Core Modes      — serious, professional, flagship modes
 *   - Situational     — context-specific threat modes
 *   - Fun / Novelty   — entertainment and character modes (collapsible)
 *
 * Selecting a card updates config.response_mode.name. Some modes carry a
 * "Supporter" badge indicating they represent enhanced VoxWatch capabilities
 * — they are fully functional without any paywall.
 *
 * When the "Custom" mode is selected a textarea appears so the user can
 * write their own AI role instruction with a character counter.
 *
 * When a dispatch-mode is selected (e.g. "police_dispatch"), a
 * "Dispatch Settings" panel appears below the mode cards. The fields in
 * that panel are stored under response_mode.dispatch in config.yaml and
 * injected into dispatch AI prompts and radio message templates at runtime.
 * All dispatch fields are optional — the pipeline works without them.
 *
 * Layout:
 *   - Core and Situational modes: 2-column grid on desktop, 1-column on mobile.
 *   - Fun modes: collapsible section, smaller cards.
 *   - Selected card has a blue ring.
 *   - Dispatch Settings panel: blue-left-border card, visible for dispatch modes.
 *   - Example quote block below the grid (hidden for custom while editing).
 *   - Custom prompt textarea + guidance info box when custom is selected.
 */

import { useRef, useState, type ChangeEvent } from 'react';
import {
  Info, Headphones, Heart, ChevronDown, ChevronUp, Radio,
  Upload, Wand2, Trash2, CheckCircle2, AlertCircle, Loader2,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { AudioPreview } from '@/components/common/AudioPreview';
import { previewAudio, generateIntroAudio, uploadIntroAudio } from '@/api/status';
import type { ResponseModeConfig, DispatchConfig, TtsConfig, ConfigValidationError } from '@/types/config';

/** Maximum recommended character count for a custom response mode prompt. */
const CUSTOM_PROMPT_MAX = 800;

/** Buy Me a Coffee support URL. */
const SUPPORT_URL = 'https://buymeacoffee.com/badbread';

/** Props for the PersonaConfigForm component. */
export interface PersonaConfigFormProps {
  /** Current response mode config value from the parent config state. */
  value: ResponseModeConfig;
  /** Callback fired whenever the user changes any response mode field. */
  onChange: (value: ResponseModeConfig) => void;
  /** Validation errors from the parent config validator (unused currently, reserved). */
  errors: ConfigValidationError[];
  /**
   * Current TTS config from the parent form, used to populate voice / provider
   * fields for the audio preview request. Optional — preview button is hidden
   * when not provided.
   */
  ttsConfig?: TtsConfig;
}

/**
 * Descriptor for a single response mode shown in the selection grid.
 */
interface ResponseModeDef {
  /** Unique identifier — matches the backend PERSONAS dict key. */
  id: string;
  /** Display name shown on the card. */
  name: string;
  /** Large emoji used as the card's visual centrepiece. */
  emoji: string;
  /** One-sentence description of the speaking style. */
  desc: string;
  /**
   * Example output quote demonstrating the mode's voice.
   * Omitted for the "custom" mode since the output is unpredictable.
   */
  example?: string;
  /**
   * When true, a "Supporter" badge is shown on the card.
   * The mode remains fully functional — the badge is informational only.
   */
  isSupporterFeature?: boolean;
}

// ---------------------------------------------------------------------------
// Mode definitions by group
// ---------------------------------------------------------------------------

/** Core modes — serious, professional, grouped first. */
const CORE_MODES: ResponseModeDef[] = [
  {
    id: 'police_dispatch',
    name: 'Police Dispatch',
    emoji: '🚔',
    desc: 'Realistic dispatch radio. Flagship mode.',
    example:
      '"All units, 10-31 in progress at 742 Elm Street. Suspect described as male, six foot, dark hoodie, blue jeans, heading east. Requesting unit respond."',
    isSupporterFeature: true,
  },
  {
    id: 'live_operator',
    name: 'Live Operator',
    emoji: '👁️',
    desc: 'Simulates real person watching cameras.',
    example:
      '"Hey — I\'ve got eyes on you right now. You in the dark hoodie near the gate. Walk away."',
  },
  {
    id: 'private_security',
    name: 'Private Security',
    emoji: '🛡️',
    desc: 'Professional, firm, liability-focused.',
    example:
      '"This is private security. You are currently on monitored premises. Please leave the area immediately."',
  },
  {
    id: 'recorded_evidence',
    name: 'Recorded Evidence',
    emoji: '⏺️',
    desc: 'Cold system logging tone.',
    example:
      '"Recording initiated. Subject identified at front entry. Male, dark jacket, estimated 6 foot. Timestamp logged."',
    isSupporterFeature: true,
  },
  {
    id: 'homeowner',
    name: 'Homeowner',
    emoji: '🏠',
    desc: 'Personal, calm, direct.',
    example: '"Hey — I can see you on camera. This is private property. Please leave now."',
  },
  {
    id: 'automated_surveillance',
    name: 'Automated Surveillance',
    emoji: '🤖',
    desc: 'Neutral AI system voice.',
    example:
      '"Surveillance system active. Unrecognized individual detected at perimeter. Authorities have been notified."',
    isSupporterFeature: true,
  },
];

/** Situational modes — context-specific threat modes. */
const SITUATIONAL_MODES: ResponseModeDef[] = [
  {
    id: 'guard_dog',
    name: 'Guard Dog Warning',
    emoji: '🐕',
    desc: 'Implies threat without stating it.',
    example:
      '"Hey — I see you on camera. Just so you know, Rex and Bruno haven\'t been fed yet today. I can let them out if you\'d like to stay."',
    isSupporterFeature: true,
  },
  {
    id: 'neighborhood_watch',
    name: 'Neighborhood Alert',
    emoji: '🏘️',
    desc: 'Community awareness pressure.',
    example:
      '"Attention — this is a neighborhood watch advisory. An unidentified individual has been observed and reported to community patrol."',
  },
];

/** Fun / Novelty modes — entertainment and character modes. */
const FUN_MODES: ResponseModeDef[] = [
  {
    id: 'mafioso',
    name: 'Italian Mafioso',
    emoji: '🤌',
    desc: 'Street-smart wiseguy. Intimidating with humor.',
    example:
      '"Hey, you in the red hoodie — you think you can just walk up to my place like that?"',
  },
  {
    id: 'tony_montana',
    name: 'Tony Montana',
    emoji: '🔫',
    desc: 'Scarface energy. Dramatic, territorial, over-the-top.',
    example:
      '"You wanna play rough? Okay! I see you in the red hoodie — you picked the wrong house, my friend."',
  },
  {
    id: 'pirate_captain',
    name: 'Pirate Captain',
    emoji: '🏴‍☠️',
    desc: 'Theatrical and threatening. Arrr!',
    example: '"Arrr! What scallywag dares approach me vessel? I see ye in yer red hoodie!"',
  },
  {
    id: 'british_butler',
    name: 'British Butler',
    emoji: '🎩',
    desc: 'Impeccably polite. Passive-aggressive perfection.',
    example:
      '"I beg your pardon, Sir, but one does not simply approach the premises uninvited."',
  },
  {
    id: 'disappointed_parent',
    name: 'Disappointed Parent',
    emoji: '😤',
    desc: 'Guilt-tripping. Makes them feel embarrassed.',
    example: '"Really? At this hour? I expected better from someone your age."',
  },
  {
    id: 'custom',
    name: 'Custom',
    emoji: '✏️',
    desc: 'Build your own character. Full control over the AI prompt.',
  },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/**
 * Supporter badge pill shown on mode cards for enhanced VoxWatch features.
 * The badge is purely informational — no functionality is locked.
 */
function SupporterBadge() {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <div className="relative inline-block">
      <button
        type="button"
        aria-label="Supporter feature — click to learn more"
        onClick={(e) => {
          e.stopPropagation();
          setShowTooltip((v) => !v);
        }}
        onBlur={() => setShowTooltip(false)}
        className={cn(
          'flex items-center gap-1 rounded-full px-1.5 py-0.5 text-xs font-medium',
          'bg-amber-100 text-amber-700 hover:bg-amber-200',
          'dark:bg-amber-900/40 dark:text-amber-400 dark:hover:bg-amber-900/60',
          'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400',
        )}
      >
        <Heart className="h-2.5 w-2.5" aria-hidden="true" />
        Supporter
      </button>

      {showTooltip && (
        <div
          role="tooltip"
          className={cn(
            'absolute bottom-full left-1/2 z-10 mb-2 w-56 -translate-x-1/2',
            'rounded-lg border border-amber-200 bg-white px-3 py-2 shadow-lg',
            'dark:border-amber-800/50 dark:bg-gray-900',
          )}
        >
          <p className="text-xs text-gray-700 dark:text-gray-300">
            This is a supporter feature. Support VoxWatch to help keep development active.
          </p>
          <a
            href={SUPPORT_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="mt-1.5 block text-xs font-medium text-amber-600 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
          >
            Support VoxWatch →
          </a>
          {/* Tooltip arrow */}
          <div className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-amber-200 dark:border-t-amber-800/50" />
        </div>
      )}
    </div>
  );
}

/**
 * A single response mode card in the selection grid.
 */
function ModeCard({
  mode,
  isSelected,
  onSelect,
  compact = false,
}: {
  mode: ResponseModeDef;
  isSelected: boolean;
  onSelect: (id: string) => void;
  compact?: boolean;
}) {
  return (
    <button
      role="radio"
      aria-checked={isSelected}
      onClick={() => onSelect(mode.id)}
      className={cn(
        'flex items-start gap-3 rounded-xl border text-left',
        'transition-all duration-150',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
        compact ? 'p-3' : 'p-4',
        isSelected
          ? [
              'border-blue-500/70 bg-blue-50 shadow-md shadow-blue-200/40 dark:bg-blue-950/30 dark:shadow-blue-900/20',
              'dark:border-blue-400/60',
            ]
          : [
              'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50 dark:border-gray-700/40 dark:bg-gray-800/40 dark:hover:border-gray-600/60 dark:hover:bg-gray-800/60',
              'hover:-translate-y-0.5 hover:shadow-sm',
            ],
      )}
    >
      {/* Emoji */}
      <span
        className={cn('flex-shrink-0 leading-none', compact ? 'mt-0.5 text-2xl' : 'mt-0.5 text-3xl')}
        aria-hidden="true"
      >
        {mode.emoji}
      </span>

      <div className="min-w-0 flex-1">
        {/* Name row with badges */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            className={cn(
              'font-semibold',
              compact ? 'text-xs' : 'text-sm',
              isSelected
                ? 'text-blue-700 dark:text-blue-300'
                : 'text-gray-900 dark:text-gray-100',
            )}
          >
            {mode.name}
          </span>
          {isSelected && (
            <span className="rounded-full bg-blue-500 px-1.5 py-0.5 text-xs font-medium text-white">
              Active
            </span>
          )}
          {mode.isSupporterFeature && <SupporterBadge />}
        </div>

        {/* Description */}
        <p
          className={cn(
            'mt-0.5 text-xs',
            isSelected
              ? 'text-blue-600 dark:text-blue-400'
              : 'text-gray-500 dark:text-gray-500',
          )}
        >
          {mode.desc}
        </p>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Dispatch mode registry
// ---------------------------------------------------------------------------

/**
 * Response mode names that activate the Dispatch Settings panel.
 * Must stay in sync with DISPATCH_MODES in voxwatch/radio_dispatch.py.
 */
const DISPATCH_MODE_IDS = new Set(['police_dispatch']);

// ---------------------------------------------------------------------------
// DispatchSettings panel
// ---------------------------------------------------------------------------

/**
 * Derive the intro source status label for the current dispatch config.
 *
 * Reflects the exact priority order used by generate_channel_intro() in
 * radio_dispatch.py so the UI always matches backend behaviour.
 *
 * Priority:
 *   1. Custom file (dispatch.intro_audio is set and non-empty)
 *   2. Cached generated intro (/data/audio/dispatch_intro_cached.wav)
 *      — the UI uses a server-side flag rather than probing the filesystem.
 *   3. Auto-generate each time
 *
 * @param introAudio - Current value of dispatch.intro_audio config field.
 * @param hasCached  - Whether the generate-and-save flow produced a cached file.
 */
function introSourceStatus(
  introAudio: string | undefined,
  hasCached: boolean,
): { label: string; color: 'green' | 'blue' | 'gray' } {
  if (introAudio && introAudio.trim()) {
    return { label: `Using custom file: ${introAudio.trim()}`, color: 'green' };
  }
  if (hasCached) {
    return { label: 'Using cached generated intro', color: 'blue' };
  }
  return { label: 'Auto-generating each time', color: 'gray' };
}

// ── DispatchIntroAudio ────────────────────────────────────────────────────────

/**
 * Props for the DispatchIntroAudio sub-component.
 */
interface DispatchIntroAudioProps {
  /** Current dispatch config — reads intro_audio, intro_text, agency. */
  value: DispatchConfig;
  /** Callback fired when intro_audio or intro_text fields change. */
  onChange: (patch: Partial<DispatchConfig>) => void;
  /** Current TTS config from the parent form (for provider/voice selection). */
  ttsConfig?: TtsConfig;
}

/**
 * Dispatch Intro Audio section — lets users choose how the channel intro is sourced.
 *
 * Three capabilities are provided:
 *
 * 1. **Status row** — shows which intro source is currently active:
 *    - Green: custom audio file is configured.
 *    - Blue:  a cached generated intro exists (saved via "Generate & Save").
 *    - Gray:  intro will be auto-generated from text on each event.
 *
 * 2. **Upload** — a file input that accepts WAV and MP3.  On submit the file
 *    is POSTed to /api/audio/upload-intro, saved to
 *    /config/audio/dispatch_intro.wav, and dispatch.intro_audio is updated in
 *    the local config so the user sees the green status immediately.  They
 *    must still Save Settings for the change to persist in config.yaml.
 *
 * 3. **Generate with AI voice** — a text field (pre-filled with dispatch.intro_text
 *    or the default "Connecting to {agency} dispatch frequency.") and a
 *    provider dropdown.  "Generate & Preview" calls /api/audio/generate-intro
 *    without save=true so the user can hear it first.  "Generate & Save"
 *    persists to /data/audio/dispatch_intro_cached.wav.
 *
 * 4. **Clear** — removes any custom file path and the cached flag, reverting
 *    to auto-generation.
 */
function DispatchIntroAudio({ value, onChange, ttsConfig }: DispatchIntroAudioProps) {
  /** File input ref used to reset the input after a successful upload. */
  const fileInputRef = useRef<HTMLInputElement>(null);

  /** Local state tracking whether a cached intro was produced this session. */
  const [hasCached, setHasCached] = useState(false);

  /** Whether the generate panel is open. */
  const [genPanelOpen, setGenPanelOpen] = useState(false);

  /** The intro text shown in the generate panel. */
  const [genText, setGenText] = useState(
    value.intro_text || 'Connecting to {agency} dispatch frequency.',
  );

  /**
   * The TTS provider chosen in the generate dropdown.  Default to the active
   * provider from ttsConfig, falling back to kokoro.
   */
  const [genProvider, setGenProvider] = useState(ttsConfig?.engine ?? 'kokoro');

  /** WAV Blob returned by the generate endpoint for browser preview. */
  const [genBlob, setGenBlob] = useState<Blob | null>(null);

  /** Audio element ref for playing the generated preview. */
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // ── Upload mutation ────────────────────────────────────────────────────────
  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadIntroAudio(file),
    onSuccess: (result) => {
      // Update the config field with the saved path so the green status shows.
      onChange({ intro_audio: result.path });
      // Reset file input.
      if (fileInputRef.current) fileInputRef.current.value = '';
    },
  });

  // ── Generate mutation ──────────────────────────────────────────────────────
  const generateMutation = useMutation({
    mutationFn: ({ save }: { save: boolean }) => {
      const provider = genProvider.toLowerCase();
      let voice: string | undefined;
      if (provider === 'kokoro') voice = ttsConfig?.kokoro_voice ?? 'af_nova';
      else if (provider === 'elevenlabs') voice = ttsConfig?.elevenlabs_voice_id ?? undefined;
      else if (provider === 'openai') voice = ttsConfig?.openai_voice ?? 'nova';
      else if (provider === 'cartesia') voice = ttsConfig?.cartesia_voice_id ?? undefined;

      return generateIntroAudio({
        text: genText,
        provider,
        voice: voice ?? '',
        speed: 0.95,
        save,
      });
    },
    onSuccess: (result) => {
      setGenBlob(result.blob);
      if (result.saved) setHasCached(true);
      // Also persist the custom intro_text to config so it survives reloads.
      onChange({ intro_text: genText });
      // Auto-play
      const url = URL.createObjectURL(result.blob);
      if (audioRef.current) {
        audioRef.current.pause();
        URL.revokeObjectURL(audioRef.current.src);
      }
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.play().catch(() => null);
    },
  });

  const status = introSourceStatus(value.intro_audio, hasCached);

  /**
   * Handle file selection from the upload input.  Validates extension before
   * triggering the upload mutation so obviously-wrong files are caught early.
   */
  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
    if (!['wav', 'mp3', 'ogg', 'flac'].includes(ext)) {
      // Show in the UI via uploadMutation error — fake an error object.
      uploadMutation.reset();
      return;
    }
    uploadMutation.mutate(file);
  }

  /**
   * Clear the custom intro path and cached flag so the pipeline reverts to
   * auto-generation.  Does not delete files from the server.
   */
  function handleClear() {
    onChange({ intro_audio: '' });
    setHasCached(false);
    setGenBlob(null);
    generateMutation.reset();
    uploadMutation.reset();
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  const statusColors = {
    green: 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-300 dark:bg-emerald-950/20 dark:border-emerald-800/40',
    blue:  'text-blue-700 bg-blue-50 border-blue-200 dark:text-blue-300 dark:bg-blue-950/20 dark:border-blue-800/40',
    gray:  'text-gray-600 bg-gray-50 border-gray-200 dark:text-gray-400 dark:bg-gray-800/40 dark:border-gray-700',
  };

  return (
    <div className="mt-4 space-y-3 border-t border-blue-200 dark:border-blue-800/40 pt-4">
      {/* Section header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-blue-600 dark:text-blue-400">
          Dispatch Intro Audio
        </p>
        {/* Clear button — only shown when a custom file or cached intro is set */}
        {(value.intro_audio || hasCached) && (
          <button
            type="button"
            onClick={handleClear}
            className={cn(
              'flex items-center gap-1 rounded-md px-2 py-1 text-xs',
              'text-red-600 hover:text-red-700 hover:bg-red-50',
              'dark:text-red-400 dark:hover:bg-red-950/20',
              'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500',
            )}
            aria-label="Clear custom intro and revert to auto-generation"
          >
            <Trash2 className="h-3 w-3" aria-hidden="true" />
            Clear
          </button>
        )}
      </div>

      {/* Current source status badge */}
      <div
        className={cn(
          'flex items-center gap-2 rounded-lg border px-3 py-2 text-xs',
          statusColors[status.color],
        )}
        aria-live="polite"
      >
        {status.color === 'green' && <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />}
        {status.color === 'blue'  && <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />}
        {status.color === 'gray'  && <Radio className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />}
        <span className="truncate">{status.label}</span>
      </div>

      {/* ── Upload custom audio ──────────────────────────────────────────────── */}
      <div>
        <p className="mb-1 text-xs font-medium text-gray-700 dark:text-gray-300">
          Upload custom audio
        </p>
        <p className="mb-2 text-xs text-gray-400 dark:text-gray-500">
          WAV or MP3. Saved to /config/audio/dispatch_intro.wav (persists across restarts).
        </p>
        <label
          className={cn(
            'flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2',
            'border-dashed border-gray-300 bg-white text-xs text-gray-600',
            'hover:border-blue-400 hover:bg-blue-50/30',
            'dark:border-gray-600 dark:bg-gray-800/40 dark:text-gray-400',
            'dark:hover:border-blue-500 dark:hover:bg-blue-950/10',
            'transition-colors',
            uploadMutation.isPending && 'opacity-60 pointer-events-none',
          )}
        >
          {uploadMutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin flex-shrink-0 text-blue-500" aria-hidden="true" />
          ) : (
            <Upload className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          )}
          <span>
            {uploadMutation.isPending
              ? 'Uploading…'
              : uploadMutation.isSuccess
                ? 'Uploaded — click to replace'
                : 'Choose WAV / MP3 file'}
          </span>
          <input
            ref={fileInputRef}
            type="file"
            accept=".wav,.mp3,.ogg,.flac,audio/wav,audio/mpeg,audio/ogg,audio/flac"
            className="sr-only"
            onChange={handleFileChange}
            disabled={uploadMutation.isPending}
          />
        </label>

        {/* Upload success feedback */}
        {uploadMutation.isSuccess && (
          <p className="mt-1 flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
            Saved to {uploadMutation.data?.path}.
            Set response_mode.dispatch.intro_audio to activate it, then save settings.
          </p>
        )}

        {/* Upload error feedback */}
        {uploadMutation.isError && (
          <p className="mt-1 flex items-center gap-1 text-xs text-red-600 dark:text-red-400">
            <AlertCircle className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
            {(uploadMutation.error as Error)?.message ?? 'Upload failed. Check file format.'}
          </p>
        )}
      </div>

      {/* ── Generate with AI voice ──────────────────────────────────────────── */}
      <div>
        <button
          type="button"
          onClick={() => setGenPanelOpen((v) => !v)}
          className={cn(
            'flex w-full items-center justify-between rounded-lg border px-3 py-2',
            'border-gray-200 bg-gray-50 text-xs font-medium text-gray-700',
            'hover:border-gray-300 hover:bg-gray-100',
            'dark:border-gray-700 dark:bg-gray-800/40 dark:text-gray-300',
            'dark:hover:border-gray-600 dark:hover:bg-gray-800/60',
            'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
          )}
          aria-expanded={genPanelOpen}
        >
          <span className="flex items-center gap-1.5">
            <Wand2 className="h-3.5 w-3.5" aria-hidden="true" />
            Generate with AI voice
          </span>
          {genPanelOpen ? (
            <ChevronUp className="h-3.5 w-3.5 text-gray-400" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-gray-400" aria-hidden="true" />
          )}
        </button>

        {genPanelOpen && (
          <div className="mt-2 space-y-3 rounded-lg border border-gray-200 bg-gray-50/60 p-3 dark:border-gray-700 dark:bg-gray-800/30">
            {/* Intro text input */}
            <div>
              <label
                htmlFor="dispatch-intro-text"
                className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
              >
                Intro phrase
              </label>
              <input
                id="dispatch-intro-text"
                type="text"
                value={genText}
                onChange={(e) => setGenText(e.target.value)}
                placeholder="Connecting to {agency} dispatch frequency."
                className={cn(
                  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                  'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                  'placeholder:text-gray-400 dark:placeholder:text-gray-500',
                )}
              />
              <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                {'{agency}'} is replaced with the configured agency name at runtime.
              </p>
            </div>

            {/* Provider selector */}
            <div>
              <label
                htmlFor="dispatch-intro-provider"
                className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
              >
                TTS provider
              </label>
              <select
                id="dispatch-intro-provider"
                value={genProvider}
                onChange={(e) => setGenProvider(e.target.value)}
                className={cn(
                  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                  'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                )}
              >
                <option value="kokoro">Kokoro (local neural)</option>
                <option value="elevenlabs">ElevenLabs (cloud, premium)</option>
                <option value="openai">OpenAI TTS (cloud)</option>
                <option value="cartesia">Cartesia (cloud)</option>
                <option value="piper">Piper (local)</option>
                <option value="espeak">eSpeak (robotic fallback)</option>
              </select>
            </div>

            {/* Action buttons */}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={!genText.trim() || generateMutation.isPending}
                onClick={() => generateMutation.mutate({ save: false })}
                className={cn(
                  'flex flex-1 items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium',
                  'border-gray-200 bg-white text-gray-700 hover:bg-gray-50',
                  'dark:border-gray-600 dark:bg-gray-800/60 dark:text-gray-300 dark:hover:bg-gray-800',
                  'disabled:opacity-50 disabled:pointer-events-none',
                  'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
                )}
              >
                {generateMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <Headphones className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {generateMutation.isPending ? 'Generating…' : 'Preview'}
              </button>

              <button
                type="button"
                disabled={!genText.trim() || generateMutation.isPending}
                onClick={() => generateMutation.mutate({ save: true })}
                className={cn(
                  'flex flex-1 items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium',
                  'border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100',
                  'dark:border-blue-700/60 dark:bg-blue-950/20 dark:text-blue-300 dark:hover:bg-blue-950/30',
                  'disabled:opacity-50 disabled:pointer-events-none',
                  'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
                )}
              >
                {generateMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <Wand2 className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {generateMutation.isPending ? 'Generating…' : 'Generate & Save'}
              </button>
            </div>

            {/* Generate result / error feedback */}
            {generateMutation.isSuccess && (
              <p
                className={cn(
                  'flex items-center gap-1 text-xs',
                  generateMutation.data.saved
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-blue-600 dark:text-blue-400',
                )}
                aria-live="polite"
              >
                <CheckCircle2 className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
                {generateMutation.data.saved
                  ? 'Saved to /data/audio/dispatch_intro_cached.wav — will be used automatically.'
                  : 'Preview playing. Use "Generate & Save" to persist for live events.'}
              </p>
            )}
            {generateMutation.isError && (
              <p className="flex items-center gap-1 text-xs text-red-600 dark:text-red-400" aria-live="polite">
                <AlertCircle className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
                {(generateMutation.error as Error)?.message ?? 'Generation failed.'}
              </p>
            )}

            {/* Hidden audio element for programmatic playback */}
            {genBlob && (
              <audio
                key={genBlob.size}
                src={URL.createObjectURL(genBlob)}
                controls
                className="w-full h-8 mt-1"
                aria-label="Generated intro preview"
              />
            )}
          </div>
        )}
      </div>

      {/* intro_audio config field (manual override / advanced) */}
      <div>
        <label
          htmlFor="dispatch-intro-audio-path"
          className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
        >
          Custom intro file path{' '}
          <span className="font-normal text-gray-400 dark:text-gray-500">(advanced)</span>
        </label>
        <input
          id="dispatch-intro-audio-path"
          type="text"
          value={value.intro_audio ?? ''}
          onChange={(e) => onChange({ intro_audio: e.target.value })}
          placeholder="/config/audio/dispatch_intro.wav"
          className={cn(
            'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono',
            'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
            'placeholder:text-gray-400 dark:placeholder:text-gray-500',
          )}
        />
        <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
          Set directly if the file already exists on the server. Overrides generated intro.
          Checked at runtime — no restart needed.
        </p>
      </div>
    </div>
  );
}

// ── DispatchSettings ──────────────────────────────────────────────────────────

/**
 * Props for the DispatchSettings component.
 */
interface DispatchSettingsProps {
  /** Current dispatch config from response_mode.dispatch. */
  value: DispatchConfig;
  /** Callback fired whenever any dispatch field changes. */
  onChange: (value: DispatchConfig) => void;
  /** TTS config from the parent form (forwarded to DispatchIntroAudio). */
  ttsConfig?: TtsConfig;
}

/**
 * Expandable panel shown when a dispatch response mode is active.
 *
 * Renders address, city, state, agency, callsign, and include_address fields
 * that are stored under `response_mode.dispatch` in config.yaml. All fields are
 * optional — the dispatch pipeline works without them, using generic fallback
 * phrasing. The full_address string is computed automatically from address +
 * city + state whenever any of those three fields change.
 *
 * Styled with a blue left border to visually distinguish it from the mode
 * cards above it.
 */
function DispatchSettings({ value, onChange, ttsConfig }: DispatchSettingsProps) {
  /**
   * Derive the full_address string from the three address components and
   * call onChange with the updated dispatch config.
   *
   * @param patch - Partial DispatchConfig fields to merge into the current value.
   */
  function update(patch: Partial<DispatchConfig>) {
    const next = { ...value, ...patch };
    // Auto-compute full_address from the component parts so the backend
    // always has a pre-assembled string it can drop into a dispatch callout.
    const parts = [next.address, next.city].filter(Boolean);
    next.full_address = parts.join(', ');
    onChange(next);
  }

  const includeAddress = value.include_address ?? true;

  return (
    <div
      className={cn(
        'rounded-xl border border-blue-200 bg-blue-50/40',
        'border-l-4 border-l-blue-500',
        'dark:border-blue-800/60 dark:bg-blue-950/15 dark:border-l-blue-400',
        'px-4 py-4',
      )}
    >
      {/* Panel header */}
      <div className="mb-3 flex items-center gap-2">
        <Radio className="h-4 w-4 flex-shrink-0 text-blue-500 dark:text-blue-400" aria-hidden="true" />
        <h5 className="text-sm font-semibold text-blue-900 dark:text-blue-200">
          Dispatch Settings
        </h5>
      </div>

      {/* Explanation */}
      <p className="mb-4 text-xs text-blue-700 dark:text-blue-400">
        Optional. When configured, your property address and agency details appear in
        the live dispatch callout — e.g. "10-97 at 123 Main Street." Leave blank to
        use generic phrasing instead.
      </p>

      <div className="space-y-3">
        {/* Address row */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {/* Street address */}
          <div className="sm:col-span-2">
            <label
              htmlFor="dispatch-address"
              className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
            >
              Property Address
            </label>
            <input
              id="dispatch-address"
              type="text"
              value={value.address ?? ''}
              onChange={(e) => update({ address: e.target.value })}
              placeholder="123 Main Street"
              className={cn(
                'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                'placeholder:text-gray-400 dark:placeholder:text-gray-500',
              )}
            />
            <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
              Used in callouts: "10-97 at [address]"
            </p>
          </div>

          {/* City */}
          <div>
            <label
              htmlFor="dispatch-city-inline"
              className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
            >
              City
            </label>
            <input
              id="dispatch-city-inline"
              type="text"
              value={value.city ?? ''}
              onChange={(e) => update({ city: e.target.value })}
              placeholder="Springfield"
              className={cn(
                'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                'placeholder:text-gray-400 dark:placeholder:text-gray-500',
              )}
            />
          </div>
        </div>

        {/* Agency + Callsign row */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {/* Agency */}
          <div>
            <label
              htmlFor="dispatch-agency"
              className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
            >
              Responding Agency{' '}
              <span className="font-normal text-gray-400 dark:text-gray-500">(optional)</span>
            </label>
            <input
              id="dispatch-agency"
              type="text"
              value={value.agency ?? ''}
              onChange={(e) => update({ agency: e.target.value })}
              placeholder="County Sheriff"
              className={cn(
                'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                'placeholder:text-gray-400 dark:placeholder:text-gray-500',
              )}
            />
            <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
              "County Sheriff dispatch..."
            </p>
          </div>

          {/* Callsign */}
          <div>
            <label
              htmlFor="dispatch-callsign"
              className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
            >
              Dispatch Callsign{' '}
              <span className="font-normal text-gray-400 dark:text-gray-500">(optional)</span>
            </label>
            <input
              id="dispatch-callsign"
              type="text"
              value={value.callsign ?? ''}
              onChange={(e) => update({ callsign: e.target.value })}
              placeholder="Unit 7"
              className={cn(
                'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                'placeholder:text-gray-400 dark:placeholder:text-gray-500',
              )}
            />
            <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
              "Unit 7, respond code 3."
            </p>
          </div>
        </div>

        {/* Include address toggle */}
        <label className="flex cursor-pointer items-start gap-3 pt-1">
          <input
            type="checkbox"
            checked={includeAddress}
            onChange={(e) => update({ include_address: e.target.checked })}
            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-700 dark:text-gray-300">
            Include address in spoken messages
            <span className="mt-0.5 block text-xs font-normal text-gray-400 dark:text-gray-500">
              When unchecked, messages use "the property" instead of the address above.
            </span>
          </span>
        </label>

        {/* Dispatcher Voice section */}
        <div className="border-t border-blue-200 dark:border-blue-800/40 pt-3 mt-1">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-blue-600 dark:text-blue-400">
            Dispatcher Voice
          </p>

          {/* Kokoro dispatcher voice */}
          {(!ttsConfig || ttsConfig.engine === 'kokoro') && (
            <div>
              <label
                htmlFor="dispatch-dispatcher-voice-kokoro"
                className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
              >
                Dispatcher Voice{' '}
                <span className="font-normal text-gray-400 dark:text-gray-500">(female recommended)</span>
              </label>
              <select
                id="dispatch-dispatcher-voice-kokoro"
                value={value.dispatcher_voice ?? 'af_bella'}
                onChange={(e) => update({ dispatcher_voice: e.target.value })}
                className={cn(
                  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                  'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                )}
              >
                <optgroup label="Female voices (recommended for dispatcher)">
                  <option value="af_bella">af_bella — warm, professional (default)</option>
                  <option value="af_sarah">af_sarah — clear, measured</option>
                  <option value="af_nicole">af_nicole — authoritative</option>
                  <option value="af_heart">af_heart — natural female</option>
                </optgroup>
                <optgroup label="Male voices">
                  <option value="am_fenrir">am_fenrir — deep male</option>
                  <option value="am_michael">am_michael — neutral male</option>
                  <option value="am_adam">am_adam — clear male</option>
                </optgroup>
              </select>
              <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                Professional female voice recommended. af_heart is too casual for dispatch.
              </p>
            </div>
          )}

          {/* OpenAI dispatcher voice */}
          {ttsConfig?.engine === 'openai' && (
            <div>
              <label
                htmlFor="dispatch-dispatcher-voice-openai"
                className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
              >
                Dispatcher Voice{' '}
                <span className="font-normal text-gray-400 dark:text-gray-500">(female recommended)</span>
              </label>
              <select
                id="dispatch-dispatcher-voice-openai"
                value={value.dispatcher_openai_voice ?? 'nova'}
                onChange={(e) => update({ dispatcher_openai_voice: e.target.value })}
                className={cn(
                  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                  'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                )}
              >
                <optgroup label="Female voices (recommended for dispatcher)">
                  <option value="nova">nova — clear female (default)</option>
                  <option value="shimmer">shimmer — warm female</option>
                  <option value="alloy">alloy — neutral</option>
                </optgroup>
                <optgroup label="Male voices">
                  <option value="echo">echo — clear male</option>
                  <option value="fable">fable — expressive male</option>
                  <option value="onyx">onyx — deep male</option>
                </optgroup>
              </select>
              <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                "nova" is clean and professional — closest to a real dispatcher voice.
              </p>
            </div>
          )}

          {/* ElevenLabs dispatcher voice */}
          {ttsConfig?.engine === 'elevenlabs' && (
            <div>
              <label
                htmlFor="dispatch-dispatcher-voice-elevenlabs"
                className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
              >
                Dispatcher Voice ID{' '}
                <span className="font-normal text-gray-400 dark:text-gray-500">(female recommended)</span>
              </label>
              <input
                id="dispatch-dispatcher-voice-elevenlabs"
                type="text"
                value={value.dispatcher_elevenlabs_voice ?? ''}
                onChange={(e) => update({ dispatcher_elevenlabs_voice: e.target.value })}
                placeholder="EXAVITQu4vr4xnSDxMaL"
                className={cn(
                  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                  'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                  'placeholder:text-gray-400 dark:placeholder:text-gray-500',
                )}
              />
              <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                ElevenLabs voice ID for the dispatcher. Default: Bella (professional female).{' '}
                <a
                  href="https://elevenlabs.io/voice-library"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-500 hover:underline dark:text-blue-400"
                >
                  Browse voice library
                </a>
              </p>
            </div>
          )}

          {ttsConfig?.engine && !['kokoro', 'openai', 'elevenlabs'].includes(ttsConfig.engine) && (
            <p className="text-xs text-gray-400 dark:text-gray-500">
              Voice selection is not available for {ttsConfig.engine}.
            </p>
          )}
        </div>

        {/* Officer Response section */}
        <div className="border-t border-blue-200 dark:border-blue-800/40 pt-3 mt-1">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-blue-600 dark:text-blue-400">
            Officer Response
          </p>
          <label className="flex cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              checked={value.officer_response ?? true}
              onChange={(e) => update({ officer_response: e.target.checked })}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500"
            />
            <span className="text-sm text-gray-700 dark:text-gray-300">
              Enable officer acknowledgment
              <span className="mt-0.5 block text-xs font-normal text-gray-400 dark:text-gray-500">
                A male officer voice responds after dispatch: "Copy dispatch. Unit seven en route."
              </span>
            </span>
          </label>

          {(value.officer_response ?? true) && (
            <div className="mt-2 space-y-3">
              {/* Officer callsign */}
              <div>
                <label
                  htmlFor="dispatch-officer-callsign"
                  className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
                >
                  Officer Callsign
                </label>
                <input
                  id="dispatch-officer-callsign"
                  type="text"
                  value={value.officer_callsign ?? ''}
                  onChange={(e) => update({ officer_callsign: e.target.value })}
                  placeholder="Unit 7"
                  className={cn(
                    'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                    'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                    'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                    'placeholder:text-gray-400 dark:placeholder:text-gray-500',
                  )}
                />
              </div>

              {/* Officer voice — shown per active TTS provider */}
              {(!ttsConfig || ttsConfig.engine === 'kokoro') && (
                <div>
                  <label
                    htmlFor="dispatch-officer-voice-kokoro"
                    className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
                  >
                    Officer Voice{' '}
                    <span className="font-normal text-gray-400 dark:text-gray-500">(male)</span>
                  </label>
                  <select
                    id="dispatch-officer-voice-kokoro"
                    value={value.officer_voice ?? 'am_fenrir'}
                    onChange={(e) => update({ officer_voice: e.target.value })}
                    className={cn(
                      'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                      'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                      'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                    )}
                  >
                    <optgroup label="Male voices (recommended for officer)">
                      <option value="am_fenrir">am_fenrir — deep male (default)</option>
                      <option value="am_michael">am_michael — neutral male</option>
                      <option value="am_adam">am_adam — clear male</option>
                    </optgroup>
                    <optgroup label="Female voices">
                      <option value="af_bella">af_bella — warm female</option>
                      <option value="af_sarah">af_sarah — clear female</option>
                      <option value="af_nicole">af_nicole — authoritative female</option>
                    </optgroup>
                  </select>
                  <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                    Deep male voice recommended to distinguish the officer from the dispatcher.
                  </p>
                </div>
              )}

              {ttsConfig?.engine === 'openai' && (
                <div>
                  <label
                    htmlFor="dispatch-officer-voice-openai"
                    className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
                  >
                    Officer Voice{' '}
                    <span className="font-normal text-gray-400 dark:text-gray-500">(male)</span>
                  </label>
                  <select
                    id="dispatch-officer-voice-openai"
                    value={value.officer_openai_voice ?? 'onyx'}
                    onChange={(e) => update({ officer_openai_voice: e.target.value })}
                    className={cn(
                      'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                      'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                      'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                    )}
                  >
                    <optgroup label="Male voices (recommended for officer)">
                      <option value="onyx">onyx — deep male (default)</option>
                      <option value="echo">echo — clear male</option>
                      <option value="fable">fable — expressive male</option>
                    </optgroup>
                    <optgroup label="Female voices">
                      <option value="nova">nova — clear female</option>
                      <option value="shimmer">shimmer — warm female</option>
                      <option value="alloy">alloy — neutral</option>
                    </optgroup>
                  </select>
                  <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                    "onyx" is the deepest male voice — best for a distinct officer sound.
                  </p>
                </div>
              )}

              {ttsConfig?.engine === 'elevenlabs' && (
                <div>
                  <label
                    htmlFor="dispatch-officer-voice-elevenlabs"
                    className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
                  >
                    Officer Voice ID{' '}
                    <span className="font-normal text-gray-400 dark:text-gray-500">(male)</span>
                  </label>
                  <input
                    id="dispatch-officer-voice-elevenlabs"
                    type="text"
                    value={value.officer_elevenlabs_voice ?? ''}
                    onChange={(e) => update({ officer_elevenlabs_voice: e.target.value })}
                    placeholder="ErXwobaYiN019PkySvjV"
                    className={cn(
                      'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono',
                      'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                      'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                      'placeholder:text-gray-400 dark:placeholder:text-gray-500',
                    )}
                  />
                  <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                    ElevenLabs voice ID for the officer. Default: Antoni (deep male).{' '}
                    <a
                      href="https://elevenlabs.io/voice-library"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-500 hover:underline dark:text-blue-400"
                    >
                      Browse voice library
                    </a>
                  </p>
                </div>
              )}

              {ttsConfig?.engine && !['kokoro', 'openai', 'elevenlabs'].includes(ttsConfig.engine) && (
                <p className="text-xs text-gray-400 dark:text-gray-500">
                  Voice selection is not available for {ttsConfig.engine}. The officer audio will
                  be pitch-shifted to sound distinct from the dispatcher.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Channel Intro toggle */}
        <label className="flex cursor-pointer items-start gap-3 pt-1">
          <input
            type="checkbox"
            checked={value.channel_intro ?? true}
            onChange={(e) => update({ channel_intro: e.target.checked })}
            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-700 dark:text-gray-300">
            Enable radio channel simulation
            <span className="mt-0.5 block text-xs font-normal text-gray-400 dark:text-gray-500">
              Plays "Connecting to dispatch frequency..." with tuning static and random chatter before the call.
            </span>
          </span>
        </label>

        {/* Dispatch Intro Audio — only shown when channel_intro is enabled */}
        {(value.channel_intro ?? true) && (
          <DispatchIntroAudio
            value={value}
            onChange={update}
            {...(ttsConfig != null ? { ttsConfig } : {})}
          />
        )}

        {/* Live preview of the computed full address */}
        {value.full_address && (
          <div className="rounded-lg border border-blue-200 bg-white/60 px-3 py-2 dark:border-blue-800/40 dark:bg-gray-800/40">
            <p className="text-xs text-gray-500 dark:text-gray-400">Preview callout</p>
            <p className="mt-0.5 text-sm font-medium text-gray-800 dark:text-gray-200">
              "All units, 10-97 at {includeAddress ? value.full_address : 'the property'}."
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

/**
 * Visual response mode selector with grouped sections, example quotes, and
 * custom prompt textarea.
 *
 * Renders Core, Situational, and Fun/Novelty mode groups. Selecting a card
 * updates config.response_mode.name. Selecting "custom" reveals a textarea
 * for config.response_mode.custom_prompt. When a dispatch mode is selected
 * (e.g. "police_dispatch"), a Dispatch Settings panel appears below the mode
 * cards with address, agency, and callsign fields stored under
 * config.response_mode.dispatch. When ttsConfig is provided, a "Preview Voice"
 * button generates a sample deterrent in-browser so the user can hear the
 * mode + voice combination.
 */
export function PersonaConfigForm({ value, onChange, ttsConfig }: PersonaConfigFormProps) {
  /** Resolved mode name — fall back to "police_dispatch" if config has no value yet. */
  const activeName = value.name || 'police_dispatch';
  /** Custom prompt text — default to empty string so textarea is always controlled. */
  const customPrompt = value.custom_prompt ?? '';
  /** Whether the active mode uses the dispatch pipeline and should show dispatch settings. */
  const isDispatchMode = DISPATCH_MODE_IDS.has(activeName);

  /** Whether the Fun / Novelty section is expanded. */
  const [funExpanded, setFunExpanded] = useState(() =>
    FUN_MODES.some((m) => m.id === activeName),
  );

  /** All modes combined for lookup. */
  const ALL_MODES = [...CORE_MODES, ...SITUATIONAL_MODES, ...FUN_MODES];

  /** Selected mode definition for rendering the example quote. */
  const activeDef = ALL_MODES.find((m) => m.id === activeName);

  /**
   * Handle a click on a mode card. Updates the name in config and
   * preserves any existing custom_prompt so the user doesn't lose their text
   * if they accidentally switch away from custom and back.
   */
  function handleSelectMode(id: string) {
    onChange({ ...value, name: id });
    // Clear audio preview when mode changes so the player doesn't show
    // stale audio for the previous mode.
    previewMutation.reset();
  }

  /**
   * Handle changes to the custom prompt textarea.
   * Updates custom_prompt in config while keeping the name as "custom".
   */
  function handleCustomPromptChange(text: string) {
    onChange({ ...value, custom_prompt: text });
  }

  /**
   * Handle changes to any Dispatch Settings field.
   * Merges the updated dispatch sub-object into the response_mode config while
   * leaving all other fields (name, custom_prompt, etc.) untouched.
   *
   * @param dispatch - Updated DispatchConfig from the DispatchSettings panel.
   */
  function handleDispatchChange(dispatch: DispatchConfig) {
    onChange({ ...value, dispatch });
  }

  // ── Audio preview ─────────────────────────────────────────────────────────
  const previewMutation = useMutation({
    mutationFn: previewAudio,
  });

  /**
   * Build and fire the preview request. Reads the active TTS provider,
   * voice, host URL, and speed from ttsConfig so the preview matches whatever
   * the user currently has configured on the TTS tab.
   */
  function handlePreview() {
    if (!ttsConfig) return;

    const provider = ttsConfig.engine || 'kokoro';
    let voice = 'af_heart';
    let providerHost: string | undefined;
    let speed = 1.0;

    if (provider === 'kokoro') {
      voice = ttsConfig.kokoro_voice ?? 'af_heart';
      providerHost = ttsConfig.kokoro_host || undefined;
      speed = ttsConfig.kokoro_speed ?? 1.0;
    } else if (provider === 'piper') {
      voice = ttsConfig.piper_model ?? 'en_US-lessac-medium';
      speed = ttsConfig.voice_speed ?? 1.0;
    } else if (provider === 'espeak') {
      voice = 'espeak';
      const wpm = ttsConfig.espeak_speed ?? 175;
      speed = wpm / 175;
    } else if (provider === 'elevenlabs') {
      voice = ttsConfig.elevenlabs_voice_id ?? 'pNInz6obpgDQGcFmaJgB';
      speed = 1.0;
    } else if (provider === 'openai') {
      voice = ttsConfig.openai_voice ?? 'onyx';
      speed = ttsConfig.openai_speed ?? 1.0;
    } else if (provider === 'cartesia') {
      voice = ttsConfig.cartesia_voice_id ?? '';
      speed = ttsConfig.cartesia_speed ?? 1.0;
    }

    // Reset any previous result before firing — ensures the AudioPreview
    // component shows the loading state immediately instead of replaying
    // stale audio from a previous persona.
    previewMutation.reset();
    previewMutation.mutate({
      persona: activeName,
      voice,
      provider,
      provider_host: providerHost,
      speed,
    });
  }

  /** Whether the preview button should be shown (TTS config available and provider is previewable). */
  const canPreview =
    !!ttsConfig &&
    ['kokoro', 'piper', 'espeak', 'elevenlabs', 'openai', 'cartesia'].includes(
      ttsConfig.engine || 'kokoro',
    );

  /** Error message extracted from the mutation error. */
  const previewError = previewMutation.isError
    ? (previewMutation.error as Error)?.message ?? 'Preview failed'
    : null;

  const charCount = customPrompt.length;
  const charCountColor =
    charCount > CUSTOM_PROMPT_MAX
      ? 'text-red-500'
      : charCount > CUSTOM_PROMPT_MAX * 0.8
        ? 'text-amber-500'
        : 'text-gray-400 dark:text-gray-500';

  return (
    <div className="space-y-6">
      {/* Section intro */}
      <p className="text-sm text-gray-500">
        The response mode changes how VoxWatch speaks — the AI still describes the real person.
      </p>

      {/* ── Voice Preview Banner ────────────────────────────────────────────── */}
      {canPreview && (
        <div className="rounded-2xl border border-gray-200 bg-gray-50 dark:border-gray-700/40 dark:bg-gray-900/60 p-4 space-y-3">
          <div className="flex items-center gap-3">
            <Headphones className="h-4 w-4 text-gray-500 dark:text-gray-400" aria-hidden="true" />
            <span className="text-xs font-semibold uppercase tracking-widest text-gray-500 dark:text-gray-400">
              Voice Preview
            </span>
            {/* Waveform animation — visible while generating */}
            {previewMutation.isPending && (
              <span className="flex items-end gap-0.5 h-5" aria-hidden="true">
                {[...Array(5)].map((_, i) => (
                  <span
                    key={i}
                    className="waveform-bar bg-green-400"
                    style={{ animationDelay: `${i * 0.12}s` }}
                  />
                ))}
              </span>
            )}
          </div>

          <AudioPreview
            audioBlob={previewMutation.data?.blob ?? null}
            isLoading={previewMutation.isPending}
            error={previewError}
            generationTimeMs={previewMutation.data?.generationTimeMs}
          />

          {!previewMutation.isPending && (
            <button
              type="button"
              onClick={handlePreview}
              className={cn(
                'flex w-full items-center justify-center gap-2.5 rounded-2xl px-6 py-3.5 text-sm font-semibold',
                'transition-all duration-200 active:scale-[0.98]',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
                previewMutation.isSuccess
                  ? [
                      'bg-green-100 border border-green-300 text-green-700 dark:bg-green-900/40 dark:border-green-700/50 dark:text-green-300',
                      'hover:bg-green-200 dark:hover:bg-green-900/60',
                    ]
                  : [
                      'bg-blue-600 text-white shadow-md shadow-blue-900/30',
                      'hover:bg-blue-500 hover:shadow-lg hover:shadow-blue-900/40 hover:-translate-y-0.5',
                    ],
              )}
            >
              <Headphones className="h-5 w-5" aria-hidden="true" />
              {previewMutation.isSuccess ? 'Regenerate Preview' : 'Preview Voice'}
            </button>
          )}

          {!previewMutation.isSuccess && !previewMutation.isError && !previewMutation.isPending && (
            <p className="text-center text-xs text-gray-500 dark:text-gray-600">
              Plays a sample clip in your browser — no camera speaker used.
            </p>
          )}
        </div>
      )}

      {/* ── Core Modes ─────────────────────────────────────────────────────── */}
      <div>
        <h5 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          Core
        </h5>
        <div
          role="radiogroup"
          aria-label="Core response mode selection"
          className="grid grid-cols-1 gap-3 sm:grid-cols-2"
        >
          {CORE_MODES.map((mode) => (
            <ModeCard
              key={mode.id}
              mode={mode}
              isSelected={activeName === mode.id}
              onSelect={handleSelectMode}
            />
          ))}
        </div>
      </div>

      {/* ── Situational Modes ──────────────────────────────────────────────── */}
      <div>
        <h5 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          Situational
        </h5>
        <div
          role="radiogroup"
          aria-label="Situational response mode selection"
          className="grid grid-cols-1 gap-3 sm:grid-cols-2"
        >
          {SITUATIONAL_MODES.map((mode) => (
            <ModeCard
              key={mode.id}
              mode={mode}
              isSelected={activeName === mode.id}
              onSelect={handleSelectMode}
            />
          ))}
        </div>
      </div>

      {/* ── Fun / Novelty Modes (collapsible) ─────────────────────────────── */}
      <div>
        <button
          type="button"
          onClick={() => setFunExpanded((v) => !v)}
          className={cn(
            'flex w-full items-center justify-between rounded-lg px-3 py-2',
            'border border-gray-200 bg-gray-50 text-left',
            'hover:bg-gray-100 dark:border-gray-700 dark:bg-gray-800/40 dark:hover:bg-gray-800/60',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
            'transition-colors',
          )}
          aria-expanded={funExpanded}
        >
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Fun / Novelty
          </span>
          {funExpanded ? (
            <ChevronUp className="h-3.5 w-3.5 text-gray-400" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-gray-400" aria-hidden="true" />
          )}
        </button>

        {funExpanded && (
          <div
            role="radiogroup"
            aria-label="Fun response mode selection"
            className="mt-2.5 grid grid-cols-1 gap-2 sm:grid-cols-2"
          >
            {FUN_MODES.map((mode) => (
              <ModeCard
                key={mode.id}
                mode={mode}
                isSelected={activeName === mode.id}
                onSelect={handleSelectMode}
                compact
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Dispatch Settings panel ────────────────────────────────────────── */}
      {isDispatchMode && (
        <DispatchSettings
          value={value.dispatch ?? {}}
          onChange={handleDispatchChange}
          {...(ttsConfig != null ? { ttsConfig } : {})}
        />
      )}

      {/* ── Example output quote ───────────────────────────────────────────── */}
      {activeDef?.example && activeName !== 'custom' && (
        <div className="rounded-2xl border border-gray-200 bg-gray-50 dark:border-gray-700/40 dark:bg-gray-900/60 px-4 py-3.5">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-gray-500 dark:text-gray-500">
            Example output
          </p>
          <blockquote className="border-l-2 border-blue-500/60 pl-3 italic text-sm text-gray-700 dark:text-gray-200">
            {activeDef.example}
          </blockquote>
          <p className="mt-2 text-xs text-gray-400 dark:text-gray-600">
            Output varies based on what the camera sees.
          </p>
        </div>
      )}

      {/* ── Custom mode editor ─────────────────────────────────────────────── */}
      {activeName === 'custom' && (
        <div className="space-y-3">
          {/* Guidance info box */}
          <div className="rounded-xl border border-blue-200 bg-blue-50/60 px-4 py-3 dark:border-blue-800/50 dark:bg-blue-950/20">
            <div className="flex items-start gap-2">
              <Info className="mt-0.5 h-4 w-4 flex-shrink-0 text-blue-500" aria-hidden="true" />
              <div className="space-y-1.5">
                <p className="text-sm font-medium text-blue-900 dark:text-blue-200">
                  Writing a custom response mode prompt
                </p>
                <p className="text-xs text-blue-700 dark:text-blue-400">
                  Write instructions for the AI's speaking style. The AI will follow your
                  response mode when describing detected persons.
                </p>
                <ul className="space-y-0.5 text-xs text-blue-700 dark:text-blue-400">
                  <li>
                    <span className="font-semibold">WHO:</span> Tell the AI who they are (e.g.
                    "You are speaking as a...")
                  </li>
                  <li>
                    <span className="font-semibold">TONE:</span> Describe the tone (e.g.
                    "intimidating", "polite", "humorous")
                  </li>
                  <li>
                    <span className="font-semibold">PHRASES:</span> Give example phrases to use
                    (e.g. "Use phrases like 'Hey you', 'pal'")
                  </li>
                  <li>
                    <span className="font-semibold">ADDRESS:</span> Say how to address the
                    person (e.g. "Hey you", "Sir", "Subject")
                  </li>
                  <li>
                    <span className="font-semibold">LENGTH:</span> Keep under 200 words for best
                    results
                  </li>
                </ul>
                <p className="text-xs text-blue-600 dark:text-blue-400">
                  The AI will still describe what the person looks like and what they are doing
                  — the response mode only changes HOW it says it.
                </p>
              </div>
            </div>
          </div>

          {/* Custom prompt textarea */}
          <div className="flex flex-col gap-1">
            <label
              htmlFor="response-mode-custom-prompt"
              className="text-xs font-medium text-gray-700 dark:text-gray-300"
            >
              Custom Response Mode Prompt
            </label>
            <textarea
              id="response-mode-custom-prompt"
              value={customPrompt}
              onChange={(e) => handleCustomPromptChange(e.target.value)}
              rows={6}
              placeholder={
                'You are speaking as a grumpy night watchman who has seen it all.\n' +
                'Use a tired, no-nonsense tone. Address the person directly.\n' +
                "Make it clear they've been spotted and you're not impressed."
              }
              className={cn(
                'w-full resize-y rounded-lg border px-3 py-2 text-sm',
                'focus:outline-none focus:ring-2 focus:ring-blue-500',
                'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100',
                charCount > CUSTOM_PROMPT_MAX
                  ? 'border-red-400 focus:border-red-400 focus:ring-red-400 dark:border-red-600'
                  : 'border-gray-300 focus:border-blue-500 dark:border-gray-600',
              )}
            />
            {/* Character counter */}
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-400 dark:text-gray-500">
                Describe who the AI is and how it should speak.
              </p>
              <span className={cn('text-xs font-mono tabular-nums', charCountColor)}>
                {charCount} / {CUSTOM_PROMPT_MAX}
              </span>
            </div>
            {charCount > CUSTOM_PROMPT_MAX && (
              <p className="text-xs text-red-500">
                Prompt is very long. The AI may ignore instructions or behave unpredictably.
                Aim for under {CUSTOM_PROMPT_MAX} characters.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
