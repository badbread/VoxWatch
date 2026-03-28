/**
 * HomeownerSettingsPanel — Settings panels for homeowner-adjacent personas.
 *
 * Exports:
 *   - MoodDef type and HOMEOWNER_MOODS constant used by the mood selector
 *   - HomeownerMoodSelector component (mood intensity chips for the homeowner persona)
 *   - LiveOperatorSettings component (operator name field for live_operator persona)
 *   - GuardDogSettings component (dog name list editor for guard_dog persona)
 */

import { cn } from '@/utils/cn';

// ---------------------------------------------------------------------------
// Homeowner mood definitions
// ---------------------------------------------------------------------------

/** A mood/attitude option for the homeowner persona. */
export interface MoodDef {
  id: string;
  label: string;
  emoji: string;
  desc: string;
  example: string;
}

/** Available homeowner moods — must match HOMEOWNER_MOODS in loader.py. */
export const HOMEOWNER_MOODS: MoodDef[] = [
  {
    id: 'observant',
    label: 'Observant',
    emoji: '👀',
    desc: 'Just narrating. No demands.',
    example: '"Hey. Just so you know, I can see you, right now, on camera. You\'re being recorded."',
  },
  {
    id: 'friendly',
    label: 'Friendly',
    emoji: '😊',
    desc: 'Warm, polite request.',
    example: '"Hey there. Everything okay? I can see you on camera. This is private property, just wanted to let you know."',
  },
  {
    id: 'firm',
    label: 'Firm',
    emoji: '😐',
    desc: 'Direct and serious. Default.',
    example: '"Hey. I can see you, on camera. This is private property. You need to leave, now."',
  },
  {
    id: 'confrontational',
    label: 'Confrontational',
    emoji: '😠',
    desc: 'Aggressive and territorial.',
    example: '"Hey! I see you, right there, on camera. What are you doing on my property? Get out. Now."',
  },
  {
    id: 'threatening',
    label: 'Threatening',
    emoji: '💀',
    desc: 'Ominous. Implies consequences.',
    example: '"You\'re on camera. I can see, everything, you\'re doing. Every second you stay, makes this worse, for you."',
  },
];

// ---------------------------------------------------------------------------
// HomeownerMoodSelector
// ---------------------------------------------------------------------------

/** Props for the HomeownerMoodSelector component. */
export interface HomeownerMoodSelectorProps {
  /** Currently selected mood id (e.g. "firm"). */
  mood: string;
  /** Callback fired when the user clicks a different mood chip. */
  onChange: (mood: string) => void;
}

/**
 * Mood selector panel shown when the Homeowner persona is active.
 * Renders a row of selectable mood chips that control the tone/intensity
 * of the homeowner persona without changing the persona itself.
 */
export function HomeownerMoodSelector({ mood, onChange }: HomeownerMoodSelectorProps) {
  const FIRM_MOOD: MoodDef = {
    id: 'firm',
    label: 'Firm',
    emoji: '😐',
    desc: 'Direct and serious.',
    example: '"I can see you on my cameras. You need to go."',
  };
  const activeMood: MoodDef = HOMEOWNER_MOODS.find((m) => m.id === mood) ?? FIRM_MOOD;

  return (
    <div className="rounded-2xl border border-blue-200 bg-blue-50/40 dark:border-blue-800/40 dark:bg-blue-950/20 px-4 py-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-lg" aria-hidden="true">🎭</span>
        <h5 className="text-xs font-semibold uppercase tracking-wide text-blue-700 dark:text-blue-400">
          Homeowner Mood
        </h5>
        <span className="text-[11px] text-gray-400 dark:text-gray-500">
          How aggressive should the message be?
        </span>
      </div>

      {/* Mood chips */}
      <div className="flex flex-wrap gap-2">
        {HOMEOWNER_MOODS.map((m) => (
          <button
            key={m.id}
            type="button"
            onClick={() => onChange(m.id)}
            className={cn(
              'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium',
              'transition-all duration-150',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
              mood === m.id
                ? 'bg-blue-600 text-white shadow-md shadow-blue-300/30 dark:shadow-blue-900/40'
                : [
                    'bg-white border border-gray-200 text-gray-700',
                    'hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700',
                    'dark:bg-gray-800 dark:border-gray-600 dark:text-gray-300',
                    'dark:hover:border-blue-600 dark:hover:bg-blue-950/30 dark:hover:text-blue-300',
                  ],
            )}
          >
            <span aria-hidden="true">{m.emoji}</span>
            {m.label}
          </button>
        ))}
      </div>

      {/* Active mood description + example */}
      <div className="rounded-xl bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-700/40 px-3 py-2.5">
        <p className="text-xs text-gray-600 dark:text-gray-400">
          <span className="font-semibold">{activeMood.label}:</span>{' '}
          {activeMood.desc}
        </p>
        <blockquote className="mt-1.5 border-l-2 border-blue-400/50 pl-2.5 text-xs italic text-gray-500 dark:text-gray-400">
          {activeMood.example}
        </blockquote>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LiveOperatorSettings
// ---------------------------------------------------------------------------

/** Props for the LiveOperatorSettings component. */
export interface LiveOperatorSettingsProps {
  /** Current value of response_mode.operator_name. */
  operatorName: string;
  /** Callback fired when the user changes the operator name field. */
  onChange: (name: string) => void;
}

/**
 * Customization panel for live_operator — operator name field.
 *
 * When set, the operator introduces themselves by name in the spoken message.
 * Leave blank for an anonymous operator.
 */
export function LiveOperatorSettings({ operatorName, onChange }: LiveOperatorSettingsProps) {
  return (
    <div className="rounded-2xl border border-green-200 bg-green-50/40 dark:border-green-800/40 dark:bg-green-950/20 px-4 py-4 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-lg" aria-hidden="true">👁️</span>
        <h5 className="text-xs font-semibold uppercase tracking-wide text-green-700 dark:text-green-400">
          Operator Name
        </h5>
      </div>
      <input
        type="text"
        value={operatorName}
        onChange={(e) => onChange(e.target.value)}
        placeholder='e.g. Mike, Sarah (says "This is Mike, I can see you...")'
        maxLength={30}
        className={cn(
          'w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm',
          'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200',
          'focus:border-green-400 focus:outline-none focus:ring-1 focus:ring-green-400',
        )}
      />
      <p className="text-[11px] text-gray-400">
        Leave blank for anonymous operator. When set, the operator introduces themselves by name.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// GuardDogSettings
// ---------------------------------------------------------------------------

/** Props for the GuardDogSettings component. */
export interface GuardDogSettingsProps {
  /** Current list of dog names from response_mode.guard_dog.dog_names. */
  dogNames: string[];
  /** Callback fired when the list of dog names changes. */
  onChange: (names: string[]) => void;
}

/**
 * Customization panel for guard_dog mode — lets users name their dogs.
 *
 * Renders a list of up to three editable name inputs with add/remove controls.
 * Named dogs are used in the spoken message: "Rex and Zeus are right inside."
 * Leave empty to fall back to generic "the dogs" phrasing.
 */
export function GuardDogSettings({ dogNames, onChange }: GuardDogSettingsProps) {
  const addDog = () => {
    if (dogNames.length < 3) onChange([...dogNames, '']);
  };
  const removeDog = (index: number) => {
    onChange(dogNames.filter((_, i) => i !== index));
  };
  const updateDog = (index: number, name: string) => {
    const updated = [...dogNames];
    updated[index] = name;
    onChange(updated);
  };

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50/40 dark:border-amber-800/40 dark:bg-amber-950/20 px-4 py-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-lg" aria-hidden="true">🐕</span>
        <h5 className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
          Dog Names
        </h5>
        <span className="text-[11px] text-gray-400 dark:text-gray-500">
          Leave empty for generic "the dogs"
        </span>
      </div>

      <div className="space-y-2">
        {dogNames.map((name, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              type="text"
              value={name}
              onChange={(e) => updateDog(i, e.target.value)}
              placeholder={`Dog ${i + 1} name`}
              maxLength={20}
              className={cn(
                'flex-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm',
                'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200',
                'focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400',
              )}
            />
            <button
              type="button"
              onClick={() => removeDog(i)}
              className="rounded-lg p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30 transition-colors"
              aria-label={`Remove dog ${i + 1}`}
            >
              <span className="text-sm">✕</span>
            </button>
          </div>
        ))}
      </div>

      {dogNames.length < 3 && (
        <button
          type="button"
          onClick={addDog}
          className={cn(
            'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium',
            'border border-dashed border-amber-300 text-amber-700',
            'hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-950/30',
            'transition-colors',
          )}
        >
          + Add Dog {dogNames.length > 0 ? `(${dogNames.length}/3)` : ''}
        </button>
      )}

      {dogNames.filter((n) => n.trim()).length > 0 && (
        <p className="text-xs text-gray-500 dark:text-gray-400 italic">
          Preview: "Just so you know,{' '}
          {dogNames.filter((n) => n.trim()).length === 1
            ? dogNames[0]
            : dogNames.filter((n) => n.trim()).length === 2
              ? `${dogNames[0]} and ${dogNames[1]}`
              : `${dogNames[0]}, ${dogNames[1]}, and ${dogNames[2]}`}{' '}
          haven't been fed yet today."
        </p>
      )}
    </div>
  );
}
