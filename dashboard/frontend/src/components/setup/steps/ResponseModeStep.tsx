/**
 * ResponseModeStep — "How should VoxWatch sound?" persona selector.
 *
 * Mirrors the PersonaConfigForm grid structure but streamlined for the wizard:
 *   - Core modes in a 2-column grid (prominently displayed)
 *   - Situational modes in a smaller row
 *   - Fun / Novelty modes behind a collapsible toggle
 *
 * The selected card shows a blue ring. An example quote updates dynamically
 * as the user clicks cards. A preview voice button lets users audition the
 * selected mode with the chosen TTS engine.
 *
 * "Live Operator" is pre-selected as the sensible default.
 * "Police Dispatch" is highlighted as the flagship special mode.
 */

import { useState } from 'react';
import {
  ChevronDown,
  ChevronUp,
  ArrowRight,
  Play,
  Loader,
  Quote,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { previewAudio } from '@/api/status';

/** Props for ResponseModeStep. */
interface ResponseModeStepProps {
  responseMode: string;
  ttsEngine: string;
  ttsVoice: string;
  onNext: (mode: string) => void;
}

// ---------------------------------------------------------------------------
// Mode definitions
// ---------------------------------------------------------------------------

interface ModeDef {
  id: string;
  name: string;
  emoji: string;
  desc: string;
  example?: string;
  isDefault?: boolean;
  isFlagship?: boolean;
}

const CORE_MODES: ModeDef[] = [
  {
    id: 'live_operator',
    name: 'Live Operator',
    emoji: '👁️',
    desc: 'Simulates a real person watching cameras.',
    example: '"Hey — I\'ve got eyes on you right now. You in the dark hoodie near the gate. Walk away."',
    isDefault: true,
  },
  {
    id: 'police_dispatch',
    name: 'Police Dispatch',
    emoji: '🚔',
    desc: 'Realistic radio scanner simulation. Flagship mode.',
    example: '"All units, 10-31 in progress. Suspect described as male, six foot, dark hoodie. Requesting unit respond."',
    isFlagship: true,
  },
  {
    id: 'private_security',
    name: 'Private Security',
    emoji: '🛡️',
    desc: 'Professional, firm, liability-focused.',
    example: '"This is private security. You are currently on monitored premises. Please leave the area immediately."',
  },
  {
    id: 'homeowner',
    name: 'Homeowner',
    emoji: '🏠',
    desc: 'Personal, calm, direct.',
    example: '"Hey — I can see you on camera. This is private property. Please leave now."',
  },
  {
    id: 'recorded_evidence',
    name: 'Recorded Evidence',
    emoji: '⏺️',
    desc: 'Cold system logging tone.',
    example: '"Recording initiated. Subject identified at front entry. Male, dark jacket. Timestamp logged."',
  },
  {
    id: 'automated_surveillance',
    name: 'Automated Surveillance',
    emoji: '🤖',
    desc: 'Neutral AI system voice.',
    example: '"Surveillance system active. Unrecognized individual detected. Authorities have been notified."',
  },
];

const SITUATIONAL_MODES: ModeDef[] = [
  {
    id: 'guard_dog',
    name: 'Guard Dog Warning',
    emoji: '🐕',
    desc: 'Implies a dog threat without stating it.',
    example: '"I see you on camera. Just so you know, Rex and Bruno haven\'t been fed yet today."',
  },
  {
    id: 'neighborhood_watch',
    name: 'Neighborhood Alert',
    emoji: '🏘️',
    desc: 'Community awareness pressure.',
    example: '"This is a neighborhood watch advisory. An unidentified individual has been observed and reported."',
  },
];

const FUN_MODES: ModeDef[] = [
  { id: 'mafioso', name: 'Italian Mafioso', emoji: '🤌', desc: 'Street-smart, intimidating with humor.', example: '"Hey, you — you think you can just walk up to my place like that?"' },
  { id: 'tony_montana', name: 'Tony Montana', emoji: '🔫', desc: 'Scarface energy. Dramatic, territorial.', example: '"You picked the wrong house, my friend."' },
  { id: 'pirate_captain', name: 'Pirate Captain', emoji: '🏴‍☠️', desc: 'Theatrical and threatening.', example: '"Arrr! What scallywag dares approach me vessel?"' },
  { id: 'british_butler', name: 'British Butler', emoji: '🎩', desc: 'Impeccably polite, passive-aggressive.', example: '"I beg your pardon, but one does not simply approach the premises uninvited."' },
  { id: 'disappointed_parent', name: 'Disappointed Parent', emoji: '😤', desc: 'Guilt-tripping and embarrassing.', example: '"Really? At this hour? I expected better from someone your age."' },
];

const ALL_MODES = [...CORE_MODES, ...SITUATIONAL_MODES, ...FUN_MODES];

/** A single mode selection card. */
function ModeCard({
  mode,
  isSelected,
  onClick,
  size = 'normal',
}: {
  mode: ModeDef;
  isSelected: boolean;
  onClick: () => void;
  size?: 'normal' | 'small';
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex flex-col items-start gap-1.5 rounded-xl border text-left transition-all',
        'focus:outline-none focus:ring-2 focus:ring-blue-500',
        size === 'normal' ? 'px-4 py-4' : 'px-3 py-3',
        isSelected
          ? 'border-blue-500 bg-blue-900/30 ring-1 ring-blue-500/50'
          : mode.isFlagship
            ? 'border-amber-700/60 bg-amber-900/10 hover:border-amber-600'
            : 'border-gray-700 bg-gray-800/50 hover:border-gray-500',
      )}
    >
      <div className="flex items-center gap-2 w-full">
        <span className={size === 'normal' ? 'text-2xl' : 'text-xl'} aria-hidden="true">
          {mode.emoji}
        </span>
        <span className={cn(
          'font-semibold leading-tight',
          size === 'normal' ? 'text-sm' : 'text-xs',
          isSelected ? 'text-blue-300' : mode.isFlagship ? 'text-amber-300' : 'text-gray-200',
        )}>
          {mode.name}
        </span>
        {mode.isFlagship && (
          <span className="ml-auto shrink-0 rounded bg-amber-900/50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400 border border-amber-700/50">
            Flagship
          </span>
        )}
        {mode.isDefault && !isSelected && (
          <span className="ml-auto shrink-0 rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-500 border border-gray-700">
            Default
          </span>
        )}
      </div>
      <p className={cn('text-gray-500 leading-relaxed', size === 'normal' ? 'text-xs' : 'text-[11px]')}>
        {mode.desc}
      </p>
    </button>
  );
}

/**
 * Response mode selector with core, situational, and fun/novelty groups.
 *
 * @example
 *   <ResponseModeStep responseMode="live_operator" ttsEngine="piper" ttsVoice="en_US-lessac-medium" onNext={...} />
 */
export function ResponseModeStep({
  responseMode: initialMode,
  ttsEngine,
  ttsVoice,
  onNext,
}: ResponseModeStepProps) {
  const [mode, setMode] = useState(initialMode);
  const [showFun, setShowFun] = useState(false);

  const selectedModeDef = ALL_MODES.find((m) => m.id === mode);

  const previewMutation = useMutation({
    mutationFn: () =>
      previewAudio({ persona: mode, voice: ttsVoice, provider: ttsEngine }),
    onSuccess: (result) => {
      const url = URL.createObjectURL(result.blob);
      const audio = new Audio(url);
      audio.play().catch(() => {});
    },
  });

  return (
    <div className="space-y-6 px-6 py-8">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-gray-100">How should VoxWatch sound?</h2>
        <p className="mt-1 text-sm text-gray-400">
          Choose a speaking style. This shapes every AI-generated warning.
          You can change it any time in Settings.
        </p>
      </div>

      {/* Core modes — 2-column grid */}
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Core modes</p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {CORE_MODES.map((m) => (
            <ModeCard key={m.id} mode={m} isSelected={mode === m.id} onClick={() => setMode(m.id)} />
          ))}
        </div>
      </div>

      {/* Situational modes */}
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Situational</p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {SITUATIONAL_MODES.map((m) => (
            <ModeCard key={m.id} mode={m} isSelected={mode === m.id} onClick={() => setMode(m.id)} />
          ))}
        </div>
      </div>

      {/* Fun / Novelty collapsible */}
      <div>
        <button
          type="button"
          onClick={() => setShowFun((v) => !v)}
          className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-500 hover:text-gray-300 transition-colors focus:outline-none"
        >
          {showFun ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          Fun / Novelty
        </button>
        {showFun && (
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {FUN_MODES.map((m) => (
              <ModeCard key={m.id} mode={m} isSelected={mode === m.id} onClick={() => setMode(m.id)} size="small" />
            ))}
          </div>
        )}
      </div>

      {/* Example quote */}
      {selectedModeDef?.example && (
        <div className="flex items-start gap-3 rounded-xl bg-gray-800/60 border border-gray-700/50 px-4 py-3">
          <Quote className="mt-0.5 h-4 w-4 shrink-0 text-blue-500" />
          <p className="text-sm italic text-gray-400 leading-relaxed">
            {selectedModeDef.example}
          </p>
        </div>
      )}

      {/* Preview voice */}
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
        {previewMutation.isPending ? 'Generating preview...' : 'Preview this voice'}
      </button>

      {/* Continue */}
      <button
        onClick={() => onNext(mode)}
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
