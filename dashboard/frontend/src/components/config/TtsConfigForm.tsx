/**
 * TtsConfigForm — Text-to-Speech engine configuration.
 *
 * Supports all 7 TTS providers:
 *   kokoro      — Neural, local or remote. Near-human quality. Recommended.
 *   piper       — Neural, local only. Good quality.
 *   elevenlabs  — Premium cloud. Best quality. Per-character billing.
 *   cartesia    — Low-latency cloud. Best time-to-first-byte.
 *   polly       — Budget cloud (Amazon Polly). Cheapest cloud option.
 *   openai      — Cloud (OpenAI TTS). Good quality, easy setup.
 *   espeak      — Robotic fallback. Always available, no deps.
 *
 * Each provider section conditionally renders its own specific fields.
 * Config keys map to config.tts.provider and config.tts.[provider_name].*.
 */

import { useState, createContext, useContext } from 'react';
import {
  ChevronDown,
  ChevronUp,
  FlaskConical,
  DollarSign,
  Zap,
  Cpu,
  Globe,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { errorForField } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import { cn } from '@/utils/cn';
import { previewAudio, testTtsProvider } from '@/api/status';
import { AudioPreview } from '@/components/common/AudioPreview';

/** Context for sharing the active persona name with sub-components. */
const PersonaContext = createContext<string>('standard');
import type { TtsConfig, ConfigValidationError } from '@/types/config';

// ---------------------------------------------------------------------------
// Provider metadata
// ---------------------------------------------------------------------------

interface ProviderMeta {
  id: string;
  label: string;
  /** One-line quality / cost / latency description. */
  tagline: string;
  /** Estimated cost per deterrent audio clip (synthesis only). */
  costPerClip: number;
  /** Typical synthesis latency category. */
  latency: 'local' | 'fast' | 'medium' | 'slow';
  /** Whether an API key is required. */
  needsApiKey: boolean;
  /** Whether the engine is always available without setup. */
  alwaysAvailable: boolean;
}

const PROVIDERS: ProviderMeta[] = [
  {
    id: 'kokoro',
    label: 'Kokoro (neural, recommended)',
    tagline: 'Near-human quality. Local or remote HTTP server. Free.',
    costPerClip: 0,
    latency: 'local',
    needsApiKey: false,
    alwaysAvailable: false,
  },
  {
    id: 'piper',
    label: 'Piper (natural voice)',
    tagline: 'Good local neural TTS. Model baked into Docker image.',
    costPerClip: 0,
    latency: 'local',
    needsApiKey: false,
    alwaysAvailable: false,
  },
  {
    id: 'elevenlabs',
    label: 'ElevenLabs (premium cloud)',
    tagline: 'Best voice quality available. Per-character billing.',
    costPerClip: 0.003,
    latency: 'medium',
    needsApiKey: true,
    alwaysAvailable: false,
  },
  {
    id: 'cartesia',
    label: 'Cartesia (fast cloud)',
    tagline: 'Fastest time-to-first-byte for real-time deterrents.',
    costPerClip: 0.0015,
    latency: 'fast',
    needsApiKey: true,
    alwaysAvailable: false,
  },
  {
    id: 'polly',
    label: 'Amazon Polly (budget cloud)',
    tagline: 'Cheapest cloud option. Neural and generative voices.',
    costPerClip: 0.0004,
    latency: 'fast',
    needsApiKey: true,
    alwaysAvailable: false,
  },
  {
    id: 'openai',
    label: 'OpenAI TTS (cloud)',
    tagline: 'Good quality, simple setup if you already have OpenAI credits.',
    costPerClip: 0.0015,
    latency: 'medium',
    needsApiKey: true,
    alwaysAvailable: false,
  },
  {
    id: 'espeak',
    label: 'eSpeak (robotic fallback)',
    tagline: 'Always available. No dependencies. Robotic sound quality.',
    costPerClip: 0,
    latency: 'local',
    needsApiKey: false,
    alwaysAvailable: true,
  },
];

// ---------------------------------------------------------------------------
// Kokoro voice data — 54 voices grouped by language
// ---------------------------------------------------------------------------

interface KokoroVoice {
  id: string;
  /** Human-readable label shown in the dropdown. */
  label: string;
  /** Quality grade (A = best, F = worst). */
  grade: string;
}

interface KokoroGroup {
  language: string;
  voices: KokoroVoice[];
}

const KOKORO_VOICE_GROUPS: KokoroGroup[] = [
  {
    language: 'American English',
    voices: [
      { id: 'af_heart',   label: 'af_heart — American Female',   grade: 'A'  },
      { id: 'af_bella',   label: 'af_bella — American Female',   grade: 'A-' },
      { id: 'af_nicole',  label: 'af_nicole — American Female',  grade: 'B-' },
      { id: 'af_sarah',   label: 'af_sarah — American Female',   grade: 'C+' },
      { id: 'af_kore',    label: 'af_kore — American Female',    grade: 'C+' },
      { id: 'af_aoede',   label: 'af_aoede — American Female',   grade: 'C+' },
      { id: 'af_alloy',   label: 'af_alloy — American Female',   grade: 'C'  },
      { id: 'af_nova',    label: 'af_nova — American Female',    grade: 'C'  },
      { id: 'af_sky',     label: 'af_sky — American Female',     grade: 'C-' },
      { id: 'af_jessica', label: 'af_jessica — American Female', grade: 'D'  },
      { id: 'af_river',   label: 'af_river — American Female',   grade: 'D'  },
      { id: 'am_michael', label: 'am_michael — American Male',   grade: 'C+' },
      { id: 'am_fenrir',  label: 'am_fenrir — American Male',    grade: 'C+' },
      { id: 'am_puck',    label: 'am_puck — American Male',      grade: 'C+' },
      { id: 'am_onyx',    label: 'am_onyx — American Male',      grade: 'D'  },
      { id: 'am_echo',    label: 'am_echo — American Male',      grade: 'D'  },
      { id: 'am_eric',    label: 'am_eric — American Male',      grade: 'D'  },
      { id: 'am_liam',    label: 'am_liam — American Male',      grade: 'D'  },
      { id: 'am_adam',    label: 'am_adam — American Male',      grade: 'F+' },
      { id: 'am_santa',   label: 'am_santa — American Male',     grade: 'D-' },
    ],
  },
  {
    language: 'British English',
    voices: [
      { id: 'bf_emma',     label: 'bf_emma — British Female',     grade: 'B-' },
      { id: 'bf_isabella', label: 'bf_isabella — British Female', grade: 'C'  },
      { id: 'bm_george',   label: 'bm_george — British Male',     grade: 'C'  },
      { id: 'bm_fable',    label: 'bm_fable — British Male',      grade: 'C'  },
      { id: 'bf_alice',    label: 'bf_alice — British Female',    grade: 'D'  },
      { id: 'bf_lily',     label: 'bf_lily — British Female',     grade: 'D'  },
      { id: 'bm_lewis',    label: 'bm_lewis — British Male',      grade: 'D+' },
      { id: 'bm_daniel',   label: 'bm_daniel — British Male',     grade: 'D'  },
    ],
  },
  {
    language: 'Japanese',
    voices: [
      { id: 'jf_alpha',     label: 'jf_alpha — Japanese Female',     grade: '' },
      { id: 'jf_gongitsune', label: 'jf_gongitsune — Japanese Female', grade: '' },
      { id: 'jf_nezumi',    label: 'jf_nezumi — Japanese Female',    grade: '' },
      { id: 'jf_tebukuro',  label: 'jf_tebukuro — Japanese Female',  grade: '' },
      { id: 'jm_kumo',      label: 'jm_kumo — Japanese Male',        grade: '' },
    ],
  },
  {
    language: 'Mandarin Chinese',
    voices: [
      { id: 'zf_xiaobei',  label: 'zf_xiaobei — Chinese Female',  grade: '' },
      { id: 'zf_xiaoni',   label: 'zf_xiaoni — Chinese Female',   grade: '' },
      { id: 'zf_xiaoxiao', label: 'zf_xiaoxiao — Chinese Female', grade: '' },
      { id: 'zf_xiaoyi',   label: 'zf_xiaoyi — Chinese Female',   grade: '' },
      { id: 'zm_yunjian',  label: 'zm_yunjian — Chinese Male',    grade: '' },
      { id: 'zm_yunxi',    label: 'zm_yunxi — Chinese Male',      grade: '' },
      { id: 'zm_yunxia',   label: 'zm_yunxia — Chinese Male',     grade: '' },
      { id: 'zm_yunyang',  label: 'zm_yunyang — Chinese Male',    grade: '' },
    ],
  },
  {
    language: 'Spanish',
    voices: [
      { id: 'ef_dora',  label: 'ef_dora — Spanish Female',  grade: '' },
      { id: 'em_alex',  label: 'em_alex — Spanish Male',    grade: '' },
      { id: 'em_santa', label: 'em_santa — Spanish Male',   grade: '' },
    ],
  },
  {
    language: 'French',
    voices: [
      { id: 'ff_siwis', label: 'ff_siwis — French Female', grade: '' },
    ],
  },
  {
    language: 'Hindi',
    voices: [
      { id: 'hf_alpha', label: 'hf_alpha — Hindi Female', grade: '' },
      { id: 'hf_beta',  label: 'hf_beta — Hindi Female',  grade: '' },
      { id: 'hm_omega', label: 'hm_omega — Hindi Male',   grade: '' },
      { id: 'hm_psi',   label: 'hm_psi — Hindi Male',     grade: '' },
    ],
  },
  {
    language: 'Italian',
    voices: [
      { id: 'if_sara',   label: 'if_sara — Italian Female', grade: '' },
      { id: 'im_nicola', label: 'im_nicola — Italian Male', grade: '' },
    ],
  },
  {
    language: 'Brazilian Portuguese',
    voices: [
      { id: 'pf_dora',  label: 'pf_dora — Portuguese Female', grade: '' },
      { id: 'pm_alex',  label: 'pm_alex — Portuguese Male',   grade: '' },
      { id: 'pm_santa', label: 'pm_santa — Portuguese Male',  grade: '' },
    ],
  },
];

// ---------------------------------------------------------------------------
// Piper voices (model baked into Docker image, displayed as reference)
// ---------------------------------------------------------------------------

const PIPER_VOICES = [
  { id: 'en_US-lessac-medium',       label: 'Lessac (Medium)',  desc: 'Clear American male. Balanced quality and speed.',        default: true },
  { id: 'en_US-lessac-high',         label: 'Lessac (High)',    desc: 'Same voice, higher quality. Slower to generate.' },
  { id: 'en_US-lessac-low',          label: 'Lessac (Low)',     desc: 'Same voice, fastest generation. Lower quality.' },
  { id: 'en_US-ryan-medium',         label: 'Ryan (Medium)',    desc: 'Deep American male. Authoritative tone.' },
  { id: 'en_US-ryan-high',           label: 'Ryan (High)',      desc: 'Same voice, higher quality. Good for security warnings.' },
  { id: 'en_US-amy-medium',          label: 'Amy (Medium)',     desc: 'American female. Clear and professional.' },
  { id: 'en_US-arctic-medium',       label: 'Arctic (Medium)',  desc: 'Neutral American. Clean and steady.' },
  { id: 'en_GB-alan-medium',         label: 'Alan (Medium)',    desc: 'British male. Formal tone.' },
  { id: 'en_GB-jenny_dioco-medium',  label: 'Jenny (Medium)',   desc: 'British female. Warm and clear.' },
  { id: 'en_GB-cori-medium',         label: 'Cori (Medium)',    desc: 'British female. Professional newsreader style.' },
] as const;

// ---------------------------------------------------------------------------
// ElevenLabs models
// ---------------------------------------------------------------------------

const ELEVENLABS_MODELS = [
  { id: 'eleven_flash_v2_5',     label: 'Flash v2.5 (fastest, lowest latency)' },
  { id: 'eleven_multilingual_v2', label: 'Multilingual v2 (best quality, 29 languages)' },
  { id: 'eleven_turbo_v2_5',     label: 'Turbo v2.5 (balanced speed / quality)' },
  { id: 'eleven_monolingual_v1', label: 'Monolingual v1 (legacy English only)' },
];

// ---------------------------------------------------------------------------
// Amazon Polly voices and regions
// ---------------------------------------------------------------------------

const POLLY_VOICES = [
  { id: 'Matthew',  label: 'Matthew (US English, Male)' },
  { id: 'Joanna',   label: 'Joanna (US English, Female)' },
  { id: 'Stephen',  label: 'Stephen (US English, Male — Generative)' },
  { id: 'Ruth',     label: 'Ruth (US English, Female — Generative)' },
  { id: 'Kevin',    label: 'Kevin (US English, Male — Neural child)' },
  { id: 'Amy',      label: 'Amy (British English, Female)' },
  { id: 'Brian',    label: 'Brian (British English, Male)' },
  { id: 'Emma',     label: 'Emma (British English, Female)' },
  { id: 'Geraint',  label: 'Geraint (Welsh English, Male)' },
  { id: 'Aria',     label: 'Aria (New Zealand English, Female)' },
  { id: 'Ayanda',   label: 'Ayanda (South African English, Female)' },
];

const AWS_REGIONS = [
  'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
  'eu-west-1', 'eu-west-2', 'eu-west-3', 'eu-central-1', 'eu-north-1',
  'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1', 'ap-northeast-2',
  'ca-central-1', 'sa-east-1',
];

// ---------------------------------------------------------------------------
// OpenAI TTS options
// ---------------------------------------------------------------------------

const OPENAI_MODELS = [
  { id: 'tts-1',    label: 'tts-1 (standard, lower latency)' },
  { id: 'tts-1-hd', label: 'tts-1-hd (high definition, slower)' },
];

const OPENAI_VOICES = [
  { id: 'alloy',   label: 'alloy — Neutral, balanced' },
  { id: 'echo',    label: 'echo — Deeper, authoritative' },
  { id: 'fable',   label: 'fable — Warm, expressive' },
  { id: 'onyx',    label: 'onyx — Deep, commanding' },
  { id: 'nova',    label: 'nova — Bright, energetic' },
  { id: 'shimmer', label: 'shimmer — Clear, pleasant' },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format estimated cost per event (worst case: 3 TTS generations per detection). */
function formatCostPerEvent(cost: number): string {
  const perEvent = cost * 3; // worst case: initial response + escalation + resolution
  if (perEvent === 0) return 'Free';
  if (perEvent < 0.001) return `<$0.001`;
  if (perEvent < 0.01)  return `~$${perEvent.toFixed(3)}`;
  return `~$${perEvent.toFixed(2)}`;
}

/** Tailwind color class for cost display. */
function costColor(cost: number): string {
  if (cost === 0)      return 'text-green-600 dark:text-green-400';
  if (cost < 0.001)    return 'text-emerald-600 dark:text-emerald-400';
  if (cost < 0.003)    return 'text-amber-600 dark:text-amber-400';
  return 'text-rose-600 dark:text-rose-400';
}

/** Tailwind color class and label for latency. */
function latencyBadge(lat: ProviderMeta['latency']): { cls: string; text: string } {
  switch (lat) {
    case 'local':  return { cls: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',   text: 'Local' };
    case 'fast':   return { cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',       text: 'Fast cloud' };
    case 'medium': return { cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',   text: 'Cloud' };
    case 'slow':   return { cls: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',       text: 'Slow cloud' };
  }
}

// ---------------------------------------------------------------------------
// Speed slider sub-component (reused by multiple providers)
// ---------------------------------------------------------------------------

function SpeedSlider({
  label,
  value,
  onChange,
  min = 0.5,
  max = 2.0,
  step = 0.05,
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint ?? `${min} = slow, 1.0 = normal, ${max} = fast`}>
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={Math.round(min * 100)}
          max={Math.round(max * 100)}
          step={Math.round(step * 100)}
          value={Math.round(value * 100)}
          onChange={(e) => onChange(Number(e.target.value) / 100)}
          className="flex-1 accent-blue-600"
        />
        <span className="w-10 font-mono text-sm text-gray-700 dark:text-gray-300">
          {value.toFixed(2)}x
        </span>
      </div>
    </Field>
  );
}

// ---------------------------------------------------------------------------
// Slider with a 0–1 range (for ElevenLabs stability / similarity)
// ---------------------------------------------------------------------------

function NormalizedSlider({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={Math.round(value * 100)}
          onChange={(e) => onChange(Number(e.target.value) / 100)}
          className="flex-1 accent-blue-600"
        />
        <span className="w-10 font-mono text-sm text-gray-700 dark:text-gray-300">
          {value.toFixed(2)}
        </span>
      </div>
    </Field>
  );
}

// ---------------------------------------------------------------------------
// Test Voice button — shared across all providers
//
// For local providers (kokoro, piper, espeak): POSTs to /api/audio/preview and
// plays the returned WAV blob in the browser via the AudioPreview component.
//
// For cloud providers (elevenlabs, cartesia, polly, openai): falls back to the
// original /api/system/test-tts endpoint which validates credentials and
// returns a JSON success/failure result (audio playback not available for
// cloud providers in the preview MVP).
// ---------------------------------------------------------------------------

/** Providers that can return playable WAV audio via the preview endpoint. */
const PREVIEWABLE_PROVIDERS = new Set(['kokoro', 'piper', 'espeak', 'elevenlabs', 'openai', 'cartesia']);

function TestVoiceButton({
  engine,
  configPayload,
  disabled,
}: {
  engine: string;
  configPayload: Record<string, string | number | undefined>;
  disabled?: boolean;
}) {
  const activePersona = useContext(PersonaContext);
  // ── Local provider path: audio preview ───────────────────────────────────
  const previewMutation = useMutation({ mutationFn: previewAudio });


  const isLocal = PREVIEWABLE_PROVIDERS.has(engine);

  const handleTest = () => {
    if (isLocal) {
      // Build a previewAudio request from the provider config payload.
      let voice = 'af_heart';
      let providerHost: string | undefined;
      let speed = 1.0;

      if (engine === 'kokoro') {
        voice = String(configPayload.kokoro_voice ?? 'af_heart');
        providerHost = configPayload.kokoro_host
          ? String(configPayload.kokoro_host)
          : undefined;
        speed = Number(configPayload.kokoro_speed ?? 1.0);
      } else if (engine === 'piper') {
        voice = String(configPayload.piper_model ?? 'en_US-lessac-medium');
        speed = Number(configPayload.voice_speed ?? 1.0);
      } else if (engine === 'espeak') {
        voice = 'espeak';
        const wpm = Number(configPayload.espeak_speed ?? 175);
        speed = wpm / 175;
      } else if (engine === 'elevenlabs') {
        voice = String(configPayload.elevenlabs_voice_id ?? 'pNInz6obpgDQGcFmaJgB');
        speed = 1.0;
      } else if (engine === 'openai') {
        voice = String(configPayload.openai_voice ?? 'onyx');
        speed = Number(configPayload.openai_speed ?? 1.0);
      } else if (engine === 'cartesia') {
        voice = String(configPayload.cartesia_voice_id ?? '');
        speed = Number(configPayload.cartesia_speed ?? 1.0);
      }

      previewMutation.mutate({
        persona: activePersona,
        voice,
        provider: engine,
        provider_host: providerHost,
        speed,
      });
    }
  };

  // ── Unified preview UI for all providers ─────────────────────────────────
  const previewError = previewMutation.isError
    ? (previewMutation.error as Error)?.message ?? 'Preview failed'
    : null;

  return (
    <div className="sm:col-span-2 space-y-2">
      {/* Audio player — visible once audio is ready, loading, or errored */}
      <AudioPreview
        audioBlob={previewMutation.data?.blob ?? null}
        isLoading={previewMutation.isPending}
        error={previewError}
        generationTimeMs={previewMutation.data?.generationTimeMs}
      />

      {/* Test Voice button — triggers synthesis; becomes "Test again" after success */}
      {!previewMutation.isPending && (
        <button
          type="button"
          onClick={handleTest}
          disabled={!!disabled}
          className={cn(
            'flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-all',
            'active:scale-[0.98] focus:outline-none focus:ring-2 focus:ring-blue-500',
            'disabled:cursor-not-allowed disabled:opacity-50',
            previewMutation.isSuccess
              ? 'border border-green-400 bg-green-50 text-green-700 hover:bg-green-100 dark:border-green-700/60 dark:bg-green-950/20 dark:text-green-300 dark:hover:bg-green-950/30'
              : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700',
          )}
        >
          <FlaskConical className="h-4 w-4" />
          {previewMutation.isSuccess ? 'Regenerate Preview' : 'Preview Voice'}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Test API Access button — cloud providers only
// ---------------------------------------------------------------------------

/**
 * "Test API Access" button for cloud TTS providers.
 *
 * Calls POST /api/audio/test-tts-provider with the given provider + key
 * and shows green success or red error feedback inline.
 */
function TestApiAccessButton({
  provider,
  apiKey,
  voiceId,
}: {
  /** TTS provider identifier (e.g. "elevenlabs", "openai", "cartesia", "polly"). */
  provider: string;
  /** API key to test.  Button is disabled when empty. */
  apiKey?: string;
  /** Optional voice ID to include in the test. */
  voiceId?: string;
}) {
  const testMutation = useMutation({ mutationFn: testTtsProvider });

  const handleTest = () => {
    testMutation.mutate({
      provider,
      ...(apiKey ? { api_key: apiKey } : {}),
      ...(voiceId ? { voice_id: voiceId } : {}),
    });
  };

  return (
    <div className="sm:col-span-2 space-y-2">
      {!testMutation.isPending && (
        <button
          type="button"
          onClick={handleTest}
          disabled={!apiKey}
          className={cn(
            'flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-all',
            'focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50',
            testMutation.isSuccess && testMutation.data?.ok
              ? 'border border-green-400 bg-green-50 text-green-700 hover:bg-green-100 dark:border-green-700/60 dark:bg-green-950/20 dark:text-green-300'
              : testMutation.isSuccess && !testMutation.data?.ok
                ? 'border border-red-400 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-700/60 dark:bg-red-950/20 dark:text-red-300'
                : 'border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-400',
          )}
        >
          {testMutation.isSuccess && testMutation.data?.ok ? (
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
          ) : testMutation.isSuccess && !testMutation.data?.ok ? (
            <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {testMutation.isSuccess
            ? testMutation.data?.ok
              ? 'API Access OK'
              : 'Access Failed'
            : 'Test API Access'}
        </button>
      )}

      {testMutation.isPending && (
        <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          Testing API access...
        </div>
      )}

      {testMutation.isSuccess && (
        <p
          className={cn(
            'text-xs',
            testMutation.data?.ok
              ? 'text-green-600 dark:text-green-400'
              : 'text-red-600 dark:text-red-400',
          )}
          aria-live="polite"
        >
          {testMutation.data?.message}
          {testMutation.data?.latency_ms ? ` (${testMutation.data.latency_ms}ms)` : ''}
        </p>
      )}

      {testMutation.isError && (
        <p className="text-xs text-red-600 dark:text-red-400" aria-live="polite">
          {(testMutation.error as Error)?.message ?? 'Test failed.'}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Provider-specific field sections
// ---------------------------------------------------------------------------

/** Kokoro fields: host URL, voice dropdown grouped by language, speed. */
function KokoroFields({
  value,
  set,
}: {
  value: TtsConfig;
  set: <K extends keyof TtsConfig>(k: K, v: TtsConfig[K]) => void;
}) {
  const [showAllVoices, setShowAllVoices] = useState(false);

  const selectedVoice = KOKORO_VOICE_GROUPS.flatMap((g) => g.voices).find(
    (v) => v.id === value.kokoro_voice,
  );

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Field
        label="Kokoro Host URL"
        hint="Leave blank for local Docker service. Set to http://host:8880 for remote."
        className="sm:col-span-2"
      >
        <input
          type="url"
          value={value.kokoro_host ?? ''}
          onChange={(e) => set('kokoro_host', e.target.value || undefined)}
          placeholder="http://kokoro-server:8880 (blank = local)"
          className={inputCls(false)}
        />
      </Field>

      <Field
        label="Voice"
        hint={selectedVoice ? `Grade: ${selectedVoice.grade || 'N/A'} — Use the list below to compare quality grades.` : undefined}
        className="sm:col-span-2"
      >
        <select
          value={value.kokoro_voice ?? 'af_heart'}
          onChange={(e) => set('kokoro_voice', e.target.value)}
          className={inputCls(false)}
        >
          {KOKORO_VOICE_GROUPS.map((group) => (
            <optgroup key={group.language} label={group.language}>
              {group.voices.map((voice) => (
                <option key={voice.id} value={voice.id}>
                  {voice.label}{voice.grade ? ` (${voice.grade})` : ''}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </Field>

      <div className="sm:col-span-2">
        <SpeedSlider
          label="Generation Speed"
          value={value.kokoro_speed ?? 1.0}
          onChange={(v) => set('kokoro_speed', v)}
        />
      </div>

      {/* Collapsible full voice list with grades */}
      <div className="sm:col-span-2 rounded-xl border border-gray-200 dark:border-gray-700/50">
        <button
          type="button"
          onClick={() => setShowAllVoices(!showAllVoices)}
          className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-medium text-gray-500 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800/30 transition-colors rounded-xl"
        >
          <span>All 54 voices with quality grades</span>
          {showAllVoices ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>

        {showAllVoices && (
          <div className="border-t border-gray-200 px-4 py-3 dark:border-gray-700/50 space-y-3">
            {KOKORO_VOICE_GROUPS.map((group) => (
              <div key={group.language}>
                <p className="mb-1.5 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                  {group.language}
                </p>
                <div className="grid grid-cols-2 gap-1 sm:grid-cols-3">
                  {group.voices.map((voice) => (
                    <button
                      key={voice.id}
                      type="button"
                      onClick={() => set('kokoro_voice', voice.id)}
                      className={cn(
                        'flex items-center justify-between rounded-md px-2 py-1 text-xs text-left transition-colors',
                        value.kokoro_voice === voice.id
                          ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200 font-semibold'
                          : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800',
                      )}
                    >
                      <span className="font-mono truncate">{voice.id}</span>
                      {voice.grade && (
                        <span className={cn(
                          'ml-1 flex-shrink-0 rounded px-1 text-xs font-bold',
                          voice.grade.startsWith('A')
                            ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                            : voice.grade.startsWith('B')
                              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                              : voice.grade.startsWith('C')
                                ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                                : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
                        )}>
                          {voice.grade}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <TestVoiceButton
        engine="kokoro"
        configPayload={{
          kokoro_host: value.kokoro_host,
          kokoro_voice: value.kokoro_voice ?? 'af_heart',
          kokoro_speed: value.kokoro_speed ?? 1.0,
        }}
      />
    </div>
  );
}

/** Piper fields: model name input, speed slider, info card about Docker rebuild. */
function PiperFields({
  value,
  set,
}: {
  value: TtsConfig;
  set: <K extends keyof TtsConfig>(k: K, v: TtsConfig[K]) => void;
}) {
  const [showVoices, setShowVoices] = useState(false);
  const currentVoice = PIPER_VOICES.find((v) => v.id === value.piper_model);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Field
        label="Voice Model"
        hint="Enter the Piper model name used at build time."
        className="sm:col-span-2"
      >
        <input
          type="text"
          value={value.piper_model}
          onChange={(e) => set('piper_model', e.target.value)}
          placeholder="en_US-lessac-medium"
          className={inputCls(false)}
        />
      </Field>

      <div className="sm:col-span-2">
        <SpeedSlider
          label="Voice Speed"
          value={value.voice_speed}
          onChange={(v) => set('voice_speed', v)}
        />
      </div>

      {/* Piper Docker rebuild info card */}
      <div className="sm:col-span-2 rounded-xl border border-blue-200 bg-blue-50/50 dark:border-blue-800/50 dark:bg-blue-950/20">
        <div className="px-4 py-3">
          <p className="text-sm font-medium text-blue-900 dark:text-blue-200">
            Current Voice: <span className="font-mono">{value.piper_model}</span>
          </p>
          {currentVoice && (
            <p className="mt-0.5 text-xs text-blue-700 dark:text-blue-400">
              {currentVoice.label} — {currentVoice.desc}
            </p>
          )}
          <p className="mt-2 text-xs text-blue-600 dark:text-blue-400">
            Piper voice models are baked into the Docker image at build time. To change
            the voice, update your{' '}
            <code className="rounded bg-blue-100 px-1 py-0.5 font-mono text-blue-800 dark:bg-blue-900/50 dark:text-blue-200">
              docker-compose.yml
            </code>{' '}
            build args and rebuild:
          </p>
          <pre className="mt-2 rounded-lg bg-gray-800 dark:bg-gray-900 p-3 text-xs text-green-400 overflow-x-auto">
{`services:
  voxwatch:
    build:
      args:
        PIPER_VOICE: en_US-ryan-medium  # Change this
    # Then rebuild:
    # docker compose build && docker compose up -d`}
          </pre>
        </div>

        <button
          type="button"
          onClick={() => setShowVoices(!showVoices)}
          className="flex w-full items-center justify-between border-t border-blue-200 px-4 py-2 text-xs font-medium text-blue-600 hover:bg-blue-100/50 dark:border-blue-800/50 dark:text-blue-400 dark:hover:bg-blue-950/30 transition-colors"
        >
          <span>Available voices ({PIPER_VOICES.length})</span>
          {showVoices ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>

        {showVoices && (
          <div className="border-t border-blue-200 px-4 py-3 dark:border-blue-800/50 space-y-1.5">
            {PIPER_VOICES.map((voice) => (
              <div
                key={voice.id}
                className={cn(
                  'flex items-start gap-2 rounded-lg px-2.5 py-1.5 text-xs',
                  voice.id === value.piper_model
                    ? 'bg-blue-100 dark:bg-blue-900/40'
                    : 'bg-transparent',
                )}
              >
                <code className={cn(
                  'flex-shrink-0 font-mono',
                  voice.id === value.piper_model
                    ? 'font-bold text-blue-800 dark:text-blue-200'
                    : 'text-gray-600 dark:text-gray-400',
                )}>
                  {voice.id}
                </code>
                <span className="text-gray-500 dark:text-gray-400">
                  — {voice.desc}
                  {'default' in voice && (
                    <span className="ml-1 rounded bg-green-100 px-1 py-0.5 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                      default
                    </span>
                  )}
                </span>
              </div>
            ))}
            <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
              Full list at <span className="font-mono">github.com/rhasspy/piper</span>
            </p>
          </div>
        )}
      </div>

      <TestVoiceButton
        engine="piper"
        configPayload={{
          piper_model: value.piper_model,
          voice_speed: value.voice_speed,
        }}
      />
    </div>
  );
}

/** ElevenLabs fields: API key, voice ID, model, stability, similarity. */
function ElevenLabsFields({
  value,
  set,
}: {
  value: TtsConfig;
  set: <K extends keyof TtsConfig>(k: K, v: TtsConfig[K]) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Field
        label="API Key"
        hint="Get your key at elevenlabs.io/settings/api-keys"
        className="sm:col-span-2"
      >
        <input
          type="password"
          value={value.elevenlabs_api_key ?? ''}
          onChange={(e) => set('elevenlabs_api_key', e.target.value || undefined)}
          placeholder="${ELEVENLABS_API_KEY}"
          autoComplete="off"
          className={inputCls(false)}
        />
      </Field>

      <Field
        label="Voice ID"
        hint="Copy the voice ID from elevenlabs.io/voice-library"
      >
        <input
          type="text"
          value={value.elevenlabs_voice_id ?? ''}
          onChange={(e) => set('elevenlabs_voice_id', e.target.value || undefined)}
          placeholder="21m00Tcm4TlvDq8ikWAM"
          className={inputCls(false)}
        />
      </Field>

      <Field label="Model">
        <select
          value={value.elevenlabs_model ?? 'eleven_flash_v2_5'}
          onChange={(e) => set('elevenlabs_model', e.target.value)}
          className={inputCls(false)}
        >
          {ELEVENLABS_MODELS.map((m) => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
        </select>
      </Field>

      <NormalizedSlider
        label="Stability"
        value={value.elevenlabs_stability ?? 0.5}
        onChange={(v) => set('elevenlabs_stability', v)}
        hint="Higher = more consistent delivery. Lower = more expressive."
      />

      <NormalizedSlider
        label="Similarity Boost"
        value={value.elevenlabs_similarity ?? 0.75}
        onChange={(v) => set('elevenlabs_similarity', v)}
        hint="Higher = closer to original voice. Too high can cause artifacts."
      />

      <TestVoiceButton
        engine="elevenlabs"
        configPayload={{
          elevenlabs_api_key:  value.elevenlabs_api_key,
          elevenlabs_voice_id: value.elevenlabs_voice_id,
          elevenlabs_model:    value.elevenlabs_model ?? 'eleven_flash_v2_5',
          elevenlabs_stability:  value.elevenlabs_stability ?? 0.5,
          elevenlabs_similarity: value.elevenlabs_similarity ?? 0.75,
        }}
        disabled={!value.elevenlabs_api_key || !value.elevenlabs_voice_id}
      />

      <TestApiAccessButton
        provider="elevenlabs"
        {...(value.elevenlabs_api_key ? { apiKey: value.elevenlabs_api_key } : {})}
        {...(value.elevenlabs_voice_id ? { voiceId: value.elevenlabs_voice_id } : {})}
      />
    </div>
  );
}

/** Cartesia fields: API key, voice ID, model, speed. */
function CartesiaFields({
  value,
  set,
}: {
  value: TtsConfig;
  set: <K extends keyof TtsConfig>(k: K, v: TtsConfig[K]) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Field
        label="API Key"
        hint="Get your key at play.cartesia.ai/keys"
        className="sm:col-span-2"
      >
        <input
          type="password"
          value={value.cartesia_api_key ?? ''}
          onChange={(e) => set('cartesia_api_key', e.target.value || undefined)}
          placeholder="${CARTESIA_API_KEY}"
          autoComplete="off"
          className={inputCls(false)}
        />
      </Field>

      <Field
        label="Voice ID"
        hint="UUID from play.cartesia.ai/voices"
      >
        <input
          type="text"
          value={value.cartesia_voice_id ?? ''}
          onChange={(e) => set('cartesia_voice_id', e.target.value || undefined)}
          placeholder="a0e99841-438c-4a64-b679-ae501e7d6091"
          className={inputCls(false)}
        />
      </Field>

      <Field label="Model" hint="sonic-2 is latest. Use sonic-english for English-only.">
        <input
          type="text"
          value={value.cartesia_model ?? 'sonic-2'}
          onChange={(e) => set('cartesia_model', e.target.value || undefined)}
          placeholder="sonic-2"
          className={inputCls(false)}
        />
      </Field>

      <div className="sm:col-span-2">
        <SpeedSlider
          label="Speed"
          value={value.cartesia_speed ?? 1.0}
          onChange={(v) => set('cartesia_speed', v)}
        />
      </div>

      <TestVoiceButton
        engine="cartesia"
        configPayload={{
          cartesia_api_key:  value.cartesia_api_key,
          cartesia_voice_id: value.cartesia_voice_id,
          cartesia_model:    value.cartesia_model ?? 'sonic-2',
          cartesia_speed:    value.cartesia_speed ?? 1.0,
        }}
        disabled={!value.cartesia_api_key || !value.cartesia_voice_id}
      />

      <TestApiAccessButton
        provider="cartesia"
        {...(value.cartesia_api_key ? { apiKey: value.cartesia_api_key } : {})}
        {...(value.cartesia_voice_id ? { voiceId: value.cartesia_voice_id } : {})}
      />
    </div>
  );
}

/** Amazon Polly fields: region, voice, engine. */
function PollyFields({
  value,
  set,
}: {
  value: TtsConfig;
  set: <K extends keyof TtsConfig>(k: K, v: TtsConfig[K]) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Field label="AWS Region" hint="Use the region closest to your server.">
        <select
          value={value.polly_region ?? 'us-east-1'}
          onChange={(e) => set('polly_region', e.target.value)}
          className={inputCls(false)}
        >
          {AWS_REGIONS.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
      </Field>

      <Field label="Synthesis Engine" hint="Generative requires supported voices only.">
        <select
          value={value.polly_engine ?? 'neural'}
          onChange={(e) => set('polly_engine', e.target.value)}
          className={inputCls(false)}
        >
          <option value="neural">neural (recommended)</option>
          <option value="generative">generative (highest quality)</option>
          <option value="standard">standard (legacy, avoid)</option>
        </select>
      </Field>

      <Field label="Voice" className="sm:col-span-2">
        <select
          value={value.polly_voice_id ?? 'Matthew'}
          onChange={(e) => set('polly_voice_id', e.target.value)}
          className={inputCls(false)}
        >
          {POLLY_VOICES.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
      </Field>

      <div className="sm:col-span-2 rounded-lg border border-amber-200 bg-amber-50/50 px-3 py-2 dark:border-amber-800/30 dark:bg-amber-950/10">
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Amazon Polly uses AWS credentials from environment variables
          (<code className="font-mono">AWS_ACCESS_KEY_ID</code> and{' '}
          <code className="font-mono">AWS_SECRET_ACCESS_KEY</code>) or an IAM role.
          Ensure the container has Polly access.
        </p>
      </div>

      <TestVoiceButton
        engine="polly"
        configPayload={{
          polly_region:   value.polly_region ?? 'us-east-1',
          polly_voice_id: value.polly_voice_id ?? 'Matthew',
          polly_engine:   value.polly_engine ?? 'neural',
        }}
      />

      {/* Polly uses AWS env var credentials — no UI API key, still testable */}
      <TestApiAccessButton
        provider="polly"
        apiKey="__env__"
      />
    </div>
  );
}

/** OpenAI TTS fields: API key, model, voice, speed. */
function OpenAiTtsFields({
  value,
  set,
}: {
  value: TtsConfig;
  set: <K extends keyof TtsConfig>(k: K, v: TtsConfig[K]) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Field
        label="API Key"
        hint="Uses the same key as your OpenAI AI provider, if configured."
        className="sm:col-span-2"
      >
        <input
          type="password"
          value={value.openai_api_key ?? ''}
          onChange={(e) => set('openai_api_key', e.target.value || undefined)}
          placeholder="${OPENAI_API_KEY}"
          autoComplete="off"
          className={inputCls(false)}
        />
      </Field>

      <Field label="Model">
        <select
          value={value.openai_model ?? 'tts-1'}
          onChange={(e) => set('openai_model', e.target.value)}
          className={inputCls(false)}
        >
          {OPENAI_MODELS.map((m) => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
        </select>
      </Field>

      <Field label="Voice">
        <select
          value={value.openai_voice ?? 'onyx'}
          onChange={(e) => set('openai_voice', e.target.value)}
          className={inputCls(false)}
        >
          {OPENAI_VOICES.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
      </Field>

      <div className="sm:col-span-2">
        <SpeedSlider
          label="Speed"
          value={value.openai_speed ?? 1.0}
          onChange={(v) => set('openai_speed', v)}
          min={0.25}
          max={4.0}
          hint="0.25 = very slow, 1.0 = normal, 4.0 = very fast"
        />
      </div>

      <TestVoiceButton
        engine="openai"
        configPayload={{
          openai_api_key: value.openai_api_key,
          openai_model:   value.openai_model ?? 'tts-1',
          openai_voice:   value.openai_voice ?? 'onyx',
          openai_speed:   value.openai_speed ?? 1.0,
        }}
        disabled={!value.openai_api_key}
      />

      <TestApiAccessButton
        provider="openai"
        {...(value.openai_api_key ? { apiKey: value.openai_api_key } : {})}
      />
    </div>
  );
}

/** eSpeak fields: WPM speed, pitch. */
function ESpeakFields({
  value,
  set,
}: {
  value: TtsConfig;
  set: <K extends keyof TtsConfig>(k: K, v: TtsConfig[K]) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Field label="Speed (words per minute)" hint="80 = very slow, 175 = normal, 450 = very fast">
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={80}
            max={450}
            step={5}
            value={value.espeak_speed ?? 175}
            onChange={(e) => set('espeak_speed', Number(e.target.value))}
            className="flex-1 accent-blue-600"
          />
          <span className="w-14 font-mono text-sm text-gray-700 dark:text-gray-300">
            {value.espeak_speed ?? 175} WPM
          </span>
        </div>
      </Field>

      <Field label="Pitch" hint="0 = lowest, 50 = default, 99 = highest">
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0}
            max={99}
            step={1}
            value={value.espeak_pitch ?? 50}
            onChange={(e) => set('espeak_pitch', Number(e.target.value))}
            className="flex-1 accent-blue-600"
          />
          <span className="w-10 font-mono text-sm text-gray-700 dark:text-gray-300">
            {value.espeak_pitch ?? 50}
          </span>
        </div>
      </Field>

      <TestVoiceButton
        engine="espeak"
        configPayload={{
          espeak_speed: value.espeak_speed ?? 175,
          espeak_pitch: value.espeak_pitch ?? 50,
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Provider info banner (quality / cost / latency summary)
// ---------------------------------------------------------------------------

function ProviderBanner({ meta }: { meta: ProviderMeta }) {
  const lat = latencyBadge(meta.latency);

  return (
    <div className="flex flex-wrap items-start gap-3 rounded-xl border border-gray-200 bg-gray-50/50 px-4 py-3 dark:border-gray-700/50 dark:bg-gray-800/30">
      <div className="flex-1">
        <p className="text-sm text-gray-700 dark:text-gray-300">{meta.tagline}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          {meta.alwaysAvailable && (
            <span className="rounded bg-green-100 px-1.5 py-0.5 font-medium text-green-700 dark:bg-green-900/30 dark:text-green-300">
              Always available
            </span>
          )}
          {meta.needsApiKey && (
            <span className="rounded bg-orange-100 px-1.5 py-0.5 font-medium text-orange-700 dark:bg-orange-900/30 dark:text-orange-300">
              Requires API key
            </span>
          )}
          <span className={cn('rounded px-1.5 py-0.5 font-medium', lat.cls)}>
            {lat.text}
          </span>
        </div>
      </div>
      <div className="text-right">
        <p className={cn('text-sm font-semibold', costColor(meta.costPerClip))}>
          <DollarSign className="mr-0.5 inline h-3.5 w-3.5" />
          {formatCostPerEvent(meta.costPerClip)}
        </p>
        <p className="text-xs text-gray-400 dark:text-gray-500">per event</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export interface TtsConfigFormProps {
  value: TtsConfig;
  onChange: (value: TtsConfig) => void;
  errors: ConfigValidationError[];
  /** Currently selected persona name — passed to preview so radio effects apply. */
  activePersona?: string;
}

/**
 * TTS engine settings form supporting all 7 providers.
 *
 * Selecting a provider from the dropdown reveals its specific config fields.
 * Each provider section has a "Test Voice" button for in-place verification.
 */
export function TtsConfigForm({ value, onChange, errors, activePersona = 'standard' }: TtsConfigFormProps) {
  /**
   * Set a single top-level TtsConfig field.
   * Uses a generic K constraint so TypeScript enforces the value type matches the key.
   */
  const set = <K extends keyof TtsConfig>(k: K, v: TtsConfig[K]) =>
    onChange({ ...value, [k]: v });

  const selectedProvider = PROVIDERS.find((p) => p.id === value.engine) ?? PROVIDERS[0]!;

  return (
    <PersonaContext.Provider value={activePersona}>
    <div className="space-y-5">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Configure the text-to-speech engine used to synthesize deterrent audio.
        Kokoro is recommended for best quality without cloud costs.
      </p>

      {/* Engine selector */}
      <Field
        label="TTS Engine"
        error={errorForField(errors, 'tts.engine')}
      >
        <select
          value={value.engine}
          onChange={(e) => set('engine', e.target.value)}
          className={inputCls(!!errorForField(errors, 'tts.engine'))}
        >
          <optgroup label="Free / Local">
            {PROVIDERS.filter((p) => p.costPerClip === 0).map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </optgroup>
          <optgroup label="Cloud (paid)">
            {PROVIDERS.filter((p) => p.costPerClip > 0).map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </optgroup>
        </select>
      </Field>

      {/* Provider info banner */}
      <ProviderBanner meta={selectedProvider} />

      {/* Provider-specific config section */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700/50 dark:bg-gray-800/20">
        {/* Section header */}
        <div className="mb-4 flex items-center gap-2">
          {selectedProvider.latency === 'local' ? (
            <Cpu className="h-4 w-4 text-blue-500" />
          ) : selectedProvider.alwaysAvailable ? (
            <Zap className="h-4 w-4 text-gray-400" />
          ) : (
            <Globe className="h-4 w-4 text-blue-500" />
          )}
          <h4 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
            {selectedProvider.label} Settings
          </h4>
        </div>

        {value.engine === 'kokoro'      && <KokoroFields    value={value} set={set} />}
        {value.engine === 'piper'       && <PiperFields     value={value} set={set} />}
        {value.engine === 'elevenlabs'  && <ElevenLabsFields value={value} set={set} />}
        {value.engine === 'cartesia'    && <CartesiaFields  value={value} set={set} />}
        {value.engine === 'polly'       && <PollyFields     value={value} set={set} />}
        {value.engine === 'openai'      && <OpenAiTtsFields value={value} set={set} />}
        {value.engine === 'espeak'      && <ESpeakFields    value={value} set={set} />}
      </div>

      {/* Global voice fallback note — reminds users per-persona voices take precedence */}
      <p className="text-xs text-gray-500 dark:text-gray-400">
        This voice is the default fallback. Each personality has its own curated voice — configure in the Personality tab.
      </p>
    </div>
    </PersonaContext.Provider>
  );
}
