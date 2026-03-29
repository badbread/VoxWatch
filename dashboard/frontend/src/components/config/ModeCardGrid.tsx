/**
 * ModeCardGrid — Response mode definitions, constants, and the ModeCard component.
 *
 * Exports all mode definition arrays, the persona voice defaults map, and the
 * ModeCard button used to render each selectable mode in the PersonaConfigForm.
 */

import { cn } from '@/utils/cn';
import type { ModeVoiceConfig } from '@/types/config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Descriptor for a single response mode shown in the selection grid.
 */
export interface ResponseModeDef {
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
   * When true, a "Customizable" chip is shown on the card indicating
   * the mode has additional settings (dog names, system name, mood, etc.).
   */
  isCustomizable?: boolean;
}

// ---------------------------------------------------------------------------
// Mode definitions by group
// ---------------------------------------------------------------------------

/** Core modes — serious, professional, grouped first. */
export const CORE_MODES: ResponseModeDef[] = [
  {
    id: 'police_dispatch',
    name: 'Police Dispatch',
    emoji: '🚔',
    desc: 'Realistic dispatch radio. Flagship mode. Best with ElevenLabs voices.',
    example:
      '"All units... 10-97 at {address}. Subject on property, dark clothing, approaching front door. Requesting nearest unit, respond."',
    isCustomizable: true,
  },
  {
    id: 'live_operator',
    name: 'Live Operator',
    emoji: '👁️',
    desc: 'Simulates real person watching cameras.',
    example:
      '"Hey. This is {operator_name}. I\'m watching you, right now, on camera. You\'re on private property. You need to leave."',
    isCustomizable: true,
  },
  {
    id: 'private_security',
    name: 'Private Security',
    emoji: '🛡️',
    desc: 'Professional, firm, liability-focused.',
    example:
      '"Attention. This is private security monitoring. You have been recorded on camera, at this location. Leave the premises immediately, or authorities will be contacted."',
  },
  {
    id: 'recorded_evidence',
    name: 'Recorded Evidence',
    emoji: '⏺️',
    desc: 'Cold system logging tone.',
    example:
      '"Recording active. Subject detected, on camera. Appearance, and location, logged. Footage has been preserved, for law enforcement."',
  },
  {
    id: 'homeowner',
    name: 'Homeowner',
    emoji: '🏠',
    desc: 'Personal, calm, direct.',
    example: '"Hey. I can see you, on my camera. This is private property. You need to leave, now."',
    isCustomizable: true,
  },
  {
    id: 'automated_surveillance',
    name: 'Automated Surveillance',
    emoji: '🤖',
    desc: 'AI system voice with robot presets.',
    example:
      '"{system_name}, active. Unrecognized individual, detected on property. Location recorded. Authorities, have been notified."',
    isCustomizable: true,
  },
];

/** Situational modes — context-specific threat modes. */
export const SITUATIONAL_MODES: ResponseModeDef[] = [
  {
    id: 'guard_dog',
    name: 'Guard Dog Warning',
    emoji: '🐕',
    desc: 'Implies threat without stating it.',
    example:
      '"Hey. I can see you, on camera. Just so you know, {dog_names}, are right inside. I can open the door, if you want to stick around."',
    isCustomizable: true,
  },
  {
    id: 'neighborhood_watch',
    name: 'Neighborhood Alert',
    emoji: '🏘️',
    desc: 'Community awareness pressure.',
    example:
      '"Attention. Neighborhood watch alert. An unidentified individual, has been spotted on camera, and reported to community patrol. Neighbors, have been notified."',
  },
];

/** Fun / Novelty modes — entertainment and character modes. */
export const FUN_MODES: ResponseModeDef[] = [
  {
    id: 'custom',
    name: 'Custom',
    emoji: '✏️',
    desc: 'Build your own character. Full control over the AI prompt.',
  },
];

// ---------------------------------------------------------------------------
// Voice defaults
// ---------------------------------------------------------------------------

/**
 * Curated default voices per persona per TTS provider.
 * These are the recommended voices for each personality.
 * Users can override in the voice section, and the global TTS voice is the final fallback.
 */
export const PERSONA_VOICE_DEFAULTS: Record<string, ModeVoiceConfig> = {
  police_dispatch:        { kokoro_voice: 'af_bella',   openai_voice: 'nova',    elevenlabs_voice: '46zEzba8Y8yQ0bVcv5O9' },
  live_operator:          { kokoro_voice: 'am_michael', openai_voice: 'onyx',    elevenlabs_voice: 'ErXwobaYiN019PkySvjV' },
  private_security:       { kokoro_voice: 'am_fenrir',  openai_voice: 'echo',    elevenlabs_voice: 'pNInz6obpgDQGcFmaJgB' },
  recorded_evidence:      { kokoro_voice: 'af_kore',    openai_voice: 'alloy' },
  homeowner:              { kokoro_voice: 'af_heart',   openai_voice: 'nova' },
  automated_surveillance: { kokoro_voice: 'af_kore',    openai_voice: 'nova' },
  guard_dog:              { kokoro_voice: 'am_adam',    openai_voice: 'onyx' },
  neighborhood_watch:     { kokoro_voice: 'af_sarah',   openai_voice: 'shimmer' },
};

// ---------------------------------------------------------------------------
// ModeCard component
// ---------------------------------------------------------------------------

/** Props for the ModeCard component. */
export interface ModeCardProps {
  /** The mode definition to render. */
  mode: ResponseModeDef;
  /** Whether this card is the currently selected mode. */
  isSelected: boolean;
  /** Callback fired when the user clicks this card. */
  onSelect: (id: string) => void;
  /**
   * When true, renders a more compact card layout suitable for the Fun/Novelty
   * collapsible section.
   */
  compact?: boolean;
}

/**
 * A single response mode card in the selection grid.
 *
 * Renders as a radio button with an emoji, mode name, badges, and a short
 * description. Selected cards receive a blue ring and background tint.
 */
export function ModeCard({ mode, isSelected, onSelect, compact = false }: ModeCardProps) {
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
          {mode.isCustomizable && (
            <span className="rounded-full bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-700 dark:bg-purple-900/40 dark:text-purple-400">
              Customizable
            </span>
          )}
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
