/**
 * SurveillanceSettingsPanel — Settings panel for the automated_surveillance persona.
 *
 * Exports the SurveillanceSettings component together with its type and constant
 * definitions. The panel lets users pick a sci-fi AI preset and set a custom
 * system name that appears in spoken output.
 */

import { cn } from '@/utils/cn';

// ---------------------------------------------------------------------------
// Types and constants
// ---------------------------------------------------------------------------

/** Descriptor for a single automated surveillance AI preset. */
export interface SurveillancePresetDef {
  id: string;
  label: string;
  emoji: string;
  desc: string;
  example: string;
  /** Optional voice recommendation shown below the preset description. */
  voiceHint?: string;
}

/** Available surveillance presets — must match backend persona logic. */
export const SURVEILLANCE_PRESETS: SurveillancePresetDef[] = [
  {
    id: 'standard',
    label: 'Standard',
    emoji: '🤖',
    desc: 'Clinical AI system. Detached and factual.',
    example: '"{system_name}, active. Subject detected, on camera. Location, recorded. Alert, has been transmitted."',
  },
  {
    id: 't800',
    label: 'T-800',
    emoji: '🦾',
    desc: 'Flat, monotone, minimal words. Terminator-inspired.',
    example: '"Target, acquired. You have been, identified. Leave the area. Now."',
  },
  {
    id: 'hal',
    label: 'HAL 9000',
    emoji: '🔴',
    desc: 'Eerily polite, unnervingly calm.',
    example: '"I\'m sorry, but, I can\'t let you stay here. I can see, everything, you\'re doing. I\'m afraid, I\'ve already notified the authorities."',
    voiceHint: 'For the best HAL experience, set TTS to Piper with the "HAL 9000" voice.',
  },
  {
    id: 'wopr',
    label: 'WOPR',
    emoji: '🎮',
    desc: 'Analytical, game-theory language. WarGames-inspired.',
    example: '"Probability of authorized access, zero. Threat assessment, in progress. Calculating, optimal response."',
  },
  {
    id: 'glados',
    label: 'GLaDOS',
    emoji: '🧪',
    desc: 'Passive-aggressive, darkly humorous.',
    example: '"Oh, how wonderful. Another test subject. I\'m recording, everything. For, science."',
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/** Props for the SurveillanceSettings component. */
export interface SurveillanceSettingsProps {
  /** Current value of response_mode.system_name. */
  systemName: string;
  /** Current value of response_mode.surveillance_preset. */
  preset: string;
  /** Callback fired when the user changes the system name field. */
  onSystemNameChange: (name: string) => void;
  /** Callback fired when the user selects a different preset chip. */
  onPresetChange: (preset: string) => void;
}

/**
 * Customization panel for automated_surveillance — system name + robot presets.
 *
 * Renders a text input for the custom system name (substituted for {system_name}
 * in spoken output) and a row of selectable preset chips inspired by iconic sci-fi
 * AI systems. The active preset's description and example quote are shown below
 * the chip row.
 */
export function SurveillanceSettings({
  systemName,
  preset,
  onSystemNameChange,
  onPresetChange,
}: SurveillanceSettingsProps) {
  const FALLBACK_PRESET: SurveillancePresetDef = {
    id: 'standard',
    label: 'Standard',
    emoji: '🤖',
    desc: 'Clinical AI system.',
    example: '',
  };
  const activePreset: SurveillancePresetDef =
    SURVEILLANCE_PRESETS.find((p) => p.id === preset) ?? FALLBACK_PRESET;

  return (
    <div className="rounded-2xl border border-purple-200 bg-purple-50/40 dark:border-purple-800/40 dark:bg-purple-950/20 px-4 py-4 space-y-3">
      {/* System name */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-lg" aria-hidden="true">🏷️</span>
          <h5 className="text-xs font-semibold uppercase tracking-wide text-purple-700 dark:text-purple-400">
            System Name
          </h5>
        </div>
        <input
          type="text"
          value={systemName}
          onChange={(e) => onSystemNameChange(e.target.value)}
          placeholder="e.g. SecBot, Sentinel, Overwatch"
          maxLength={30}
          className={cn(
            'w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm',
            'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200',
            'focus:border-purple-400 focus:outline-none focus:ring-1 focus:ring-purple-400',
          )}
        />
        <p className="text-[11px] text-gray-400">Leave blank for generic "Surveillance system"</p>
      </div>

      {/* Preset selector */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-lg" aria-hidden="true">🎭</span>
          <h5 className="text-xs font-semibold uppercase tracking-wide text-purple-700 dark:text-purple-400">
            AI Preset
          </h5>
          <span className="text-[11px] text-gray-400 dark:text-gray-500">
            Inspired by iconic sci-fi AI
          </span>
        </div>

        <div className="flex flex-wrap gap-2">
          {SURVEILLANCE_PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onPresetChange(p.id)}
              className={cn(
                'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium',
                'transition-all duration-150',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500',
                preset === p.id
                  ? 'bg-purple-600 text-white shadow-md shadow-purple-300/30 dark:shadow-purple-900/40'
                  : [
                      'bg-white border border-gray-200 text-gray-700',
                      'hover:border-purple-300 hover:bg-purple-50 hover:text-purple-700',
                      'dark:bg-gray-800 dark:border-gray-600 dark:text-gray-300',
                      'dark:hover:border-purple-600 dark:hover:bg-purple-950/30 dark:hover:text-purple-300',
                    ],
              )}
            >
              <span aria-hidden="true">{p.emoji}</span>
              {p.label}
            </button>
          ))}
        </div>

        <div className="rounded-xl bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-700/40 px-3 py-2.5">
          <p className="text-xs text-gray-600 dark:text-gray-400">
            <span className="font-semibold">{activePreset.label}:</span>{' '}
            {activePreset.desc}
          </p>
          {activePreset.example && (
            <blockquote className="mt-1.5 border-l-2 border-purple-400/50 pl-2.5 text-xs italic text-gray-500 dark:text-gray-400">
              {activePreset.example}
            </blockquote>
          )}
          {activePreset.voiceHint && (
            <p className="mt-2 flex items-center gap-1.5 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/40 px-2.5 py-1.5 text-xs text-amber-700 dark:text-amber-400">
              <span aria-hidden="true">💡</span>
              {activePreset.voiceHint}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
