/**
 * TtsProviderStep — Text-to-Speech engine selection.
 *
 * Engines are split into two groups:
 *   Free / Local:  Piper (default), Kokoro (recommended upgrade), eSpeak (fallback)
 *   Cloud:         ElevenLabs, Cartesia, Polly, OpenAI TTS
 *
 * Piper is pre-selected because it works out of the box with no setup.
 * A prominent recommendation banner points users toward Kokoro for near-human
 * quality (free, local) and ElevenLabs for premium cloud quality.
 *
 * A voice preview button is shown for engines where the backend can synthesise
 * a sample clip.
 */

import { useState } from 'react';
import {
  Volume2,
  Cpu,
  Globe,
  Star,
  ArrowRight,
  Loader,
  Play,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { previewAudio } from '@/api/status';

/** Props for TtsProviderStep. */
interface TtsProviderStepProps {
  ttsEngine: string;
  ttsVoice: string;
  responseMode: string;
  onNext: (engine: string, voice: string) => void;
}

// ---------------------------------------------------------------------------
// Engine metadata
// ---------------------------------------------------------------------------

interface VoiceOption {
  id: string;
  label: string;
  recommended?: boolean;
}

interface TtsEngineDef {
  id: string;
  label: string;
  tagline: string;
  group: 'local' | 'cloud';
  icon: React.ElementType;
  voices: VoiceOption[];
  needsApiKey?: boolean;
}

const TTS_ENGINES: TtsEngineDef[] = [
  {
    id: 'piper',
    label: 'Piper',
    tagline: 'Natural neural voice. Built into Docker image. Zero setup.',
    group: 'local',
    icon: Cpu,
    voices: [
      { id: 'en_US-lessac-medium', label: 'Lessac (medium)', recommended: true },
      { id: 'en_US-lessac-high', label: 'Lessac (high quality)' },
      { id: 'en_US-ryan-high', label: 'Ryan (male)' },
      { id: 'en_GB-alan-medium', label: 'Alan (British)' },
    ],
  },
  {
    id: 'kokoro',
    label: 'Kokoro',
    tagline: 'Near-human quality. Free. Requires separate Kokoro server.',
    group: 'local',
    icon: Star,
    voices: [
      { id: 'af_heart', label: 'Heart (female)', recommended: true },
      { id: 'af_bella', label: 'Bella (female)' },
      { id: 'am_fenrir', label: 'Fenrir (deep male)' },
      { id: 'am_michael', label: 'Michael (male)' },
    ],
  },
  {
    id: 'espeak',
    label: 'eSpeak',
    tagline: 'Robotic fallback. Always available, no external dependencies.',
    group: 'local',
    icon: Cpu,
    voices: [
      { id: 'en', label: 'English (default)', recommended: true },
      { id: 'en-us', label: 'English US' },
      { id: 'en-gb', label: 'English GB' },
    ],
  },
  {
    id: 'elevenlabs',
    label: 'ElevenLabs',
    tagline: 'Best voice quality available. Requires API key.',
    group: 'cloud',
    icon: Globe,
    needsApiKey: true,
    voices: [
      { id: 'Rachel', label: 'Rachel (female, calm)', recommended: true },
      { id: 'Adam', label: 'Adam (male, deep)' },
      { id: 'Bella', label: 'Bella (female, soft)' },
    ],
  },
  {
    id: 'cartesia',
    label: 'Cartesia',
    tagline: 'Fastest cloud latency. Great for real-time deterrents.',
    group: 'cloud',
    icon: Globe,
    needsApiKey: true,
    voices: [
      { id: 'default', label: 'Default voice', recommended: true },
    ],
  },
  {
    id: 'polly',
    label: 'Amazon Polly',
    tagline: 'Budget cloud. Requires AWS credentials.',
    group: 'cloud',
    icon: Globe,
    needsApiKey: true,
    voices: [
      { id: 'Matthew', label: 'Matthew (male)', recommended: true },
      { id: 'Joanna', label: 'Joanna (female)' },
    ],
  },
  {
    id: 'openai',
    label: 'OpenAI TTS',
    tagline: 'Good cloud quality. Uses your OpenAI API key.',
    group: 'cloud',
    icon: Globe,
    needsApiKey: true,
    voices: [
      { id: 'alloy', label: 'Alloy (neutral)', recommended: true },
      { id: 'echo', label: 'Echo (male)' },
      { id: 'nova', label: 'Nova (female)' },
      { id: 'onyx', label: 'Onyx (deep male)' },
    ],
  },
];

const LOCAL_ENGINES = TTS_ENGINES.filter((e) => e.group === 'local');
const CLOUD_ENGINES = TTS_ENGINES.filter((e) => e.group === 'cloud');

const inputCls = cn(
  'w-full rounded-lg border bg-gray-800 px-3 py-3 text-base text-gray-100',
  'border-gray-600 placeholder-gray-500',
  'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50',
);

/**
 * TTS engine selector with local/cloud grouping and voice preview.
 *
 * @example
 *   <TtsProviderStep ttsEngine="piper" ttsVoice="en_US-lessac-medium" responseMode="live_operator" onNext={...} />
 */
export function TtsProviderStep({
  ttsEngine: initialEngine,
  ttsVoice: initialVoice,
  responseMode,
  onNext,
}: TtsProviderStepProps) {
  const [engine, setEngine] = useState(initialEngine);
  const [voice, setVoice] = useState(initialVoice);

  const engineDef = TTS_ENGINES.find((e) => e.id === engine);

  const handleEngineChange = (newEngine: string) => {
    setEngine(newEngine);
    const def = TTS_ENGINES.find((e) => e.id === newEngine);
    const defaultVoice = def?.voices.find((v) => v.recommended) ?? def?.voices[0];
    setVoice(defaultVoice?.id ?? '');
  };

  const previewMutation = useMutation({
    mutationFn: () =>
      previewAudio({
        persona: responseMode,
        voice,
        provider: engine,
      }),
    onSuccess: (result) => {
      const url = URL.createObjectURL(result.blob);
      const audio = new Audio(url);
      audio.play().catch(() => {/* user gesture required on some browsers */});
    },
  });

  const EngineCard = ({ def }: { def: TtsEngineDef }) => {
    const Icon = def.icon;
    const isSelected = engine === def.id;
    return (
      <button
        key={def.id}
        type="button"
        onClick={() => handleEngineChange(def.id)}
        className={cn(
          'flex flex-col gap-1 rounded-xl border px-4 py-3 text-left transition-all',
          'focus:outline-none focus:ring-2 focus:ring-blue-500',
          isSelected
            ? 'border-blue-500 bg-blue-900/30'
            : 'border-gray-700 bg-gray-800/50 hover:border-gray-500',
        )}
      >
        <div className="flex items-center gap-2">
          <Icon className={cn('h-4 w-4', isSelected ? 'text-blue-400' : 'text-gray-500')} />
          <span className={cn('text-sm font-semibold', isSelected ? 'text-blue-300' : 'text-gray-200')}>
            {def.label}
          </span>
        </div>
        <p className="text-xs text-gray-500 leading-relaxed">{def.tagline}</p>
      </button>
    );
  };

  return (
    <div className="space-y-6 px-6 py-8">
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-600/20 text-emerald-400">
          <Volume2 className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-100">Text-to-Speech engine</h2>
          <p className="mt-1 text-sm text-gray-400">
            Choose how VoxWatch speaks through your camera speakers.
          </p>
        </div>
      </div>

      {/* Recommendation banners */}
      <div className="space-y-2">
        <div className="flex items-start gap-2.5 rounded-xl bg-emerald-900/20 border border-emerald-700/40 px-4 py-3">
          <Star className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
          <p className="text-sm text-emerald-300">
            <strong>Want near-human voice quality?</strong> Try Kokoro — free, runs locally,
            sounds dramatically better than Piper.
          </p>
        </div>
        <div className="flex items-start gap-2.5 rounded-xl bg-blue-900/20 border border-blue-700/40 px-4 py-3">
          <Globe className="mt-0.5 h-4 w-4 shrink-0 text-blue-400" />
          <p className="text-sm text-blue-300">
            <strong>Want premium quality?</strong> ElevenLabs has the best voices available
            — worth it for Police Dispatch mode.
          </p>
        </div>
      </div>

      {/* Free / Local engines */}
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          Free / Local
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {LOCAL_ENGINES.map((def) => <EngineCard key={def.id} def={def} />)}
        </div>
      </div>

      {/* Cloud engines */}
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          Cloud (API key required)
        </p>
        <div className="grid grid-cols-2 gap-2">
          {CLOUD_ENGINES.map((def) => <EngineCard key={def.id} def={def} />)}
        </div>
      </div>

      {/* Voice selector */}
      {engineDef && engineDef.voices.length > 1 && (
        <div>
          <label htmlFor="tts-voice" className="mb-1.5 block text-sm font-medium text-gray-300">
            Voice
          </label>
          <select
            id="tts-voice"
            value={voice}
            onChange={(e) => { setVoice(e.target.value); }}
            className={inputCls}
          >
            {engineDef.voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}{v.recommended ? ' (Recommended)' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Voice preview */}
      <button
        type="button"
        onClick={() => previewMutation.mutate()}
        disabled={previewMutation.isPending}
        className={cn(
          'flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold',
          'border border-gray-600 bg-gray-800 text-gray-300 hover:bg-gray-700',
          'transition-all active:scale-[0.98]',
          'focus:outline-none focus:ring-2 focus:ring-blue-500',
          'disabled:cursor-not-allowed disabled:opacity-50',
        )}
      >
        {previewMutation.isPending ? (
          <Loader className="h-4 w-4 animate-spin" />
        ) : (
          <Play className="h-4 w-4" />
        )}
        {previewMutation.isPending ? 'Generating preview...' : 'Preview voice'}
      </button>

      {/* Continue */}
      <button
        onClick={() => onNext(engine, voice)}
        className={cn(
          'flex w-full items-center justify-center gap-3 rounded-xl px-6 py-4',
          'bg-blue-600 hover:bg-blue-500 text-base font-semibold text-white',
          'transition-all duration-150 active:scale-[0.98]',
          'focus:outline-none focus:ring-2 focus:ring-blue-400',
        )}
      >
        Continue
        <ArrowRight className="h-5 w-5" />
      </button>
    </div>
  );
}
