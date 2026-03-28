/**
 * DispatchSettingsPanel — Expandable settings panel for the police_dispatch persona.
 *
 * Exports the DispatchSettings component (shown when a dispatch mode is active)
 * and its embedded DispatchIntroAudio sub-component. Also exports the set of
 * mode IDs that activate this panel so PersonaConfigForm can reference it without
 * duplicating the list.
 *
 * These fields are stored under response_mode.dispatch in config.yaml and
 * injected into dispatch AI prompts and radio message templates at runtime.
 * All dispatch fields are optional — the pipeline works without them.
 */

import { useRef, useState, type ChangeEvent } from 'react';
import {
  Headphones, ChevronDown, ChevronUp, Radio,
  Upload, Wand2, Trash2, CheckCircle2, AlertCircle, Loader2,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { generateIntroAudio, uploadIntroAudio } from '@/api/status';
import type { DispatchConfig, TtsConfig } from '@/types/config';

// ---------------------------------------------------------------------------
// Dispatch mode registry
// ---------------------------------------------------------------------------

/**
 * Response mode names that activate the Dispatch Settings panel.
 * Must stay in sync with DISPATCH_MODES in voxwatch/radio_dispatch.py.
 */
export const DISPATCH_MODE_IDS = new Set(['police_dispatch']);

// ---------------------------------------------------------------------------
// ElevenLabs voice presets for dispatch roles
// ---------------------------------------------------------------------------

/** ElevenLabs dispatcher voice presets — curated for realistic police dispatch. */
export const ELEVENLABS_DISPATCHER_PRESETS = [
  { id: '46zEzba8Y8yQ0bVcv5O9', label: 'Steady Dispatcher — Female (recommended)' },
  { id: 'EXAVITQu4vr4xnSDxMaL', label: 'Bella — Professional Female' },
  { id: 'jBpfAFnaylXS2mapolut', label: 'Dispatch Operator — Female' },
  { id: '21m00Tcm4TlvDq8ikWAM', label: 'Rachel — Calm Female' },
];

/** ElevenLabs officer voice presets — curated for responding officer segments. */
export const ELEVENLABS_OFFICER_PRESETS = [
  { id: 'ErXwobaYiN019PkySvjV', label: 'Antoni — Authoritative Male (recommended)' },
  { id: '9CuE3aTXEwR00eVzenBK', label: 'Vet Sergeant — Gruff Male' },
  { id: 'VR6AewLTigWG4xSOukaG', label: 'Arnold — Deep Male' },
  { id: 'pNInz6obpgDQGcFmaJgB', label: 'Adam — Commanding Male' },
  { id: 'yoZ06aMxZJJ28mfd3POQ', label: 'Sam — Gruff Male' },
];

// ---------------------------------------------------------------------------
// Helpers
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

// ---------------------------------------------------------------------------
// DispatchIntroAudio
// ---------------------------------------------------------------------------

/**
 * Props for the DispatchIntroAudio sub-component.
 */
export interface DispatchIntroAudioProps {
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
export function DispatchIntroAudio({ value, onChange, ttsConfig }: DispatchIntroAudioProps) {
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

// ---------------------------------------------------------------------------
// DispatchSettings
// ---------------------------------------------------------------------------

/**
 * Props for the DispatchSettings component.
 */
export interface DispatchSettingsProps {
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
export function DispatchSettings({ value, onChange, ttsConfig }: DispatchSettingsProps) {
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
                Dispatcher Voice
              </label>
              <select
                id="dispatch-dispatcher-voice-elevenlabs"
                value={ELEVENLABS_DISPATCHER_PRESETS.some((p) => p.id === (value.dispatcher_elevenlabs_voice ?? ''))
                  ? (value.dispatcher_elevenlabs_voice ?? '')
                  : (value.dispatcher_elevenlabs_voice ? '__custom__' : '')}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === '__custom__') return; // user will type below
                  update({ dispatcher_elevenlabs_voice: v });
                }}
                className={cn(
                  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                  'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                )}
              >
                <optgroup label="Police / Dispatch">
                  {ELEVENLABS_DISPATCHER_PRESETS.map((p) => (
                    <option key={p.id} value={p.id}>{p.label}</option>
                  ))}
                </optgroup>
                <optgroup label="Other">
                  <option value="__custom__">Custom Voice ID...</option>
                </optgroup>
              </select>
              {/* Show text input if custom or unrecognized voice ID */}
              {(value.dispatcher_elevenlabs_voice && !ELEVENLABS_DISPATCHER_PRESETS.some((p) => p.id === value.dispatcher_elevenlabs_voice)) && (
                <input
                  type="text"
                  value={value.dispatcher_elevenlabs_voice ?? ''}
                  onChange={(e) => update({ dispatcher_elevenlabs_voice: e.target.value })}
                  placeholder="Paste ElevenLabs voice ID"
                  className={cn(
                    'mt-1.5 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono',
                    'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                    'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                    'placeholder:text-gray-400 dark:placeholder:text-gray-500',
                  )}
                />
              )}
              <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                Voice used for all dispatch call segments.
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
                    Officer Voice
                  </label>
                  <select
                    id="dispatch-officer-voice-elevenlabs"
                    value={ELEVENLABS_OFFICER_PRESETS.some((p) => p.id === (value.officer_elevenlabs_voice ?? ''))
                      ? (value.officer_elevenlabs_voice ?? '')
                      : (value.officer_elevenlabs_voice ? '__custom__' : '')}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === '__custom__') return;
                      update({ officer_elevenlabs_voice: v });
                    }}
                    className={cn(
                      'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm',
                      'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                      'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                    )}
                  >
                    <optgroup label="Police / Officer">
                      {ELEVENLABS_OFFICER_PRESETS.map((p) => (
                        <option key={p.id} value={p.id}>{p.label}</option>
                      ))}
                    </optgroup>
                    <optgroup label="Other">
                      <option value="__custom__">Custom Voice ID...</option>
                    </optgroup>
                  </select>
                  {(value.officer_elevenlabs_voice && !ELEVENLABS_OFFICER_PRESETS.some((p) => p.id === value.officer_elevenlabs_voice)) && (
                    <input
                      type="text"
                      value={value.officer_elevenlabs_voice ?? ''}
                      onChange={(e) => update({ officer_elevenlabs_voice: e.target.value })}
                      placeholder="Paste ElevenLabs voice ID"
                      className={cn(
                        'mt-1.5 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono',
                        'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                        'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                        'placeholder:text-gray-400 dark:placeholder:text-gray-500',
                      )}
                    />
                  )}
                  <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                    Voice used for the responding officer segment.
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
