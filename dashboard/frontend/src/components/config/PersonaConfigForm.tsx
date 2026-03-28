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
 *
 * Sub-components live in neighbouring files:
 *   - ModeCardGrid.tsx         — ResponseModeDef, mode arrays, ModeCard, PERSONA_VOICE_DEFAULTS
 *   - DispatchSettingsPanel.tsx — DispatchSettings, DispatchIntroAudio, DISPATCH_MODE_IDS
 *   - SurveillanceSettingsPanel.tsx — SurveillanceSettings, SURVEILLANCE_PRESETS
 *   - HomeownerSettingsPanel.tsx   — HomeownerMoodSelector, LiveOperatorSettings, GuardDogSettings
 */

import { useEffect, useState } from 'react';
import { Info, ChevronDown, ChevronUp, Volume2 } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { previewAudio } from '@/api/status';
import { AudioPreview } from '@/components/common/AudioPreview';
import type { ResponseModeConfig, DispatchConfig, TtsConfig, ConfigValidationError } from '@/types/config';

import {
  ModeCard,
  CORE_MODES,
  SITUATIONAL_MODES,
  FUN_MODES,
  PERSONA_VOICE_DEFAULTS,
} from './ModeCardGrid';
import { DispatchSettings, DISPATCH_MODE_IDS } from './DispatchSettingsPanel';
import { SurveillanceSettings, SURVEILLANCE_PRESETS } from './SurveillanceSettingsPanel';
import {
  HomeownerMoodSelector,
  LiveOperatorSettings,
  GuardDogSettings,
  HOMEOWNER_MOODS,
} from './HomeownerSettingsPanel';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maximum recommended character count for a custom response mode prompt. */
const CUSTOM_PROMPT_MAX = 800;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Preview helpers
// ---------------------------------------------------------------------------

/**
 * Substitute persona template variables with user-configured values.
 * Mirrors the backend _substitute_vars logic so "what you see is what you hear".
 */
function substitutePreviewVars(text: string, config: ResponseModeConfig): string {
  let result = text;
  // Guard dog names — format as natural Oxford-comma list
  const dogNames = (config.guard_dog?.dog_names ?? []).filter((n): n is string => Boolean(n));
  let dogStr = 'the dogs';
  if (dogNames.length === 1) dogStr = dogNames[0]!;
  else if (dogNames.length === 2) dogStr = `${dogNames[0]} and ${dogNames[1]}`;
  else if (dogNames.length >= 3) dogStr = `${dogNames.slice(0, -1).join(', ')}, and ${dogNames[dogNames.length - 1]}`;
  result = result.replaceAll('{dog_names}', dogStr);
  result = result.replaceAll('{system_name}', config.system_name || 'Surveillance system');
  result = result.replaceAll('{operator_name}', config.operator_name || 'the operator');
  // Dispatch address substitution
  const addr = config.dispatch?.full_address || config.dispatch?.address || '742 Elm Street';
  result = result.replaceAll('{address}', addr);
  const agency = config.dispatch?.agency || 'County dispatch';
  result = result.replaceAll('{agency}', agency);
  return result;
}

/**
 * Get the best preview text for the current persona + customization state.
 * Prioritises mood/preset-specific examples over the generic mode example.
 */
function getPreviewText(activeName: string, value: ResponseModeConfig): string | null {
  const ALL = [...CORE_MODES, ...SITUATIONAL_MODES, ...FUN_MODES];
  const modeDef = ALL.find((m) => m.id === activeName);

  // Homeowner moods have their own example quotes
  if (activeName === 'homeowner') {
    const mood = value.mood ?? 'firm';
    const moodDef = HOMEOWNER_MOODS.find((m) => m.id === mood);
    if (moodDef) return substitutePreviewVars(moodDef.example.replace(/^"|"$/g, ''), value);
  }

  // Surveillance presets have their own example quotes
  if (activeName === 'automated_surveillance') {
    const preset = value.surveillance_preset ?? 'standard';
    const presetDef = SURVEILLANCE_PRESETS.find((p) => p.id === preset);
    if (presetDef?.example) return substitutePreviewVars(presetDef.example.replace(/^"|"$/g, ''), value);
  }

  // Fall back to the mode's generic example
  if (modeDef?.example) {
    return substitutePreviewVars(modeDef.example.replace(/^"|"$/g, ''), value);
  }

  return null;
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

  /** Audio preview mutation — same pattern as TtsConfigForm. */
  const previewMutation = useMutation({ mutationFn: previewAudio });

  // Reset preview state when switching between personas so stale audio /
  // error messages from one persona don't bleed into another.
  useEffect(() => {
    previewMutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeName]);

  // ── Voice override helpers ─────────────────────────────────────────────────
  // Computed once per render; used by both the voice selector panel and the
  // Preview Voice button so the resolved voice is always consistent.

  const _engine = ttsConfig?.engine ?? 'kokoro';

  /**
   * Resolves the effective voice — always uses the global TTS config voice.
   * Per-persona overrides are only available for police_dispatch (handled
   * separately in DispatchSettings).
   */
  function resolveEffectiveVoice(): string {
    if (_engine === 'kokoro')     return ttsConfig?.kokoro_voice ?? 'af_heart';
    if (_engine === 'openai')     return ttsConfig?.openai_voice ?? 'onyx';
    if (_engine === 'elevenlabs') return ttsConfig?.elevenlabs_voice_id ?? '';
    if (_engine === 'piper')      return ttsConfig?.piper_model ?? 'en_US-lessac-medium';
    return '';
  }

  const _effectiveVoice = resolveEffectiveVoice();

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
        The personality changes how VoxWatch speaks — the AI still describes the real person.
      </p>

      {/* Voice preview available via TTS/Personality > Test Voice on the Tests page */}

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

      {/* ── Homeowner Mood selector ────────────────────────────────────────── */}
      {activeName === 'homeowner' && (
        <HomeownerMoodSelector
          mood={value.mood ?? 'firm'}
          onChange={(mood) => onChange({ ...value, mood })}
        />
      )}

      {/* ── Guard Dog settings ─────────────────────────────────────────────── */}
      {activeName === 'guard_dog' && (
        <GuardDogSettings
          dogNames={value.guard_dog?.dog_names ?? []}
          onChange={(dog_names) => onChange({ ...value, guard_dog: { ...value.guard_dog, dog_names } })}
        />
      )}

      {/* ── Automated Surveillance settings ────────────────────────────────── */}
      {activeName === 'automated_surveillance' && (
        <SurveillanceSettings
          systemName={value.system_name ?? ''}
          preset={value.surveillance_preset ?? 'standard'}
          onSystemNameChange={(system_name) => onChange({ ...value, system_name })}
          onPresetChange={(surveillance_preset) => onChange({ ...value, surveillance_preset })}
        />
      )}

      {/* ── Live Operator settings ─────────────────────────────────────────── */}
      {activeName === 'live_operator' && (
        <LiveOperatorSettings
          operatorName={value.operator_name ?? ''}
          onChange={(operator_name) => onChange({ ...value, operator_name })}
        />
      )}

      {/* ── Example output quote ───────────────────────────────────────────── */}
      {activeDef?.example && activeName !== 'custom' && (
        <div className="rounded-2xl border border-gray-200 bg-gray-50 dark:border-gray-700/40 dark:bg-gray-900/60 px-4 py-3.5">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-gray-500 dark:text-gray-500">
            Example output
          </p>
          <blockquote className="border-l-2 border-blue-500/60 pl-3 italic text-sm text-gray-700 dark:text-gray-200">
            {substitutePreviewVars(activeDef.example, value)}
          </blockquote>
          <p className="mt-2 text-xs text-gray-400 dark:text-gray-600">
            Output varies based on what the camera sees.
          </p>
        </div>
      )}

      {/* ── Voice suggestion ─────────────────────────────────────────────── */}
      {activeName !== 'custom' && activeName !== 'police_dispatch' && ttsConfig && (
        (() => {
          const suggestion = PERSONA_VOICE_DEFAULTS[activeName];
          const suggestedVoice =
            _engine === 'kokoro' ? suggestion?.kokoro_voice :
            _engine === 'openai' ? suggestion?.openai_voice :
            _engine === 'elevenlabs' ? suggestion?.elevenlabs_voice :
            null;
          if (!suggestedVoice) return null;
          return (
            <div className="flex items-start gap-2 rounded-xl border border-blue-200 bg-blue-50/50 px-4 py-2.5 dark:border-blue-800/40 dark:bg-blue-950/20">
              <span className="mt-0.5 flex-shrink-0 text-blue-500" aria-hidden="true">💡</span>
              <p className="text-xs text-blue-700 dark:text-blue-400">
                <span className="font-medium">Suggested voice:</span>{' '}
                <code className="rounded bg-blue-100 px-1 py-0.5 font-mono text-blue-800 dark:bg-blue-900/50 dark:text-blue-200">
                  {suggestedVoice}
                </code>
                {' '}({_engine}) — change in the TTS tab to apply globally.
              </p>
            </div>
          );
        })()
      )}

      {/* ── Audio preview ──────────────────────────────────────────────────── */}
      {activeName !== 'custom' && ttsConfig && (
        <div className="space-y-2">
          {/* AudioPreview player — visible when audio is ready, loading, or errored */}
          <AudioPreview
            audioBlob={previewMutation.data?.blob ?? null}
            isLoading={previewMutation.isPending}
            error={previewMutation.isError ? (previewMutation.error as Error)?.message ?? 'Preview failed' : null}
            generationTimeMs={previewMutation.data?.generationTimeMs}
            {...(previewMutation.data?.fallbackUsed != null ? { fallbackUsed: previewMutation.data.fallbackUsed } : {})}
            {...(previewMutation.data?.actualProvider ? { actualProvider: previewMutation.data.actualProvider } : {})}
            configuredProvider={ttsConfig?.engine}
            {...(previewMutation.data?.fallbackReason ? { fallbackReason: previewMutation.data.fallbackReason } : {})}
            proxyFallback={previewMutation.data?.proxyFallback ?? false}
          />

          {/* Preview Voice button — uses per-persona voice override → curated default → global TTS config. */}
          {!previewMutation.isPending && (
            <button
              type="button"
              onClick={() => {
                const text = getPreviewText(activeName, value);
                if (!text || !ttsConfig) return;

                // Use the voice helpers computed in the component body (_effectiveVoice,
                // _engine) so the preview uses the exact same resolution logic as the
                // voice selector panel above.
                let voice = _effectiveVoice || 'af_heart';
                let speed = 1.0;

                if (_engine === 'kokoro') {
                  speed = ttsConfig.kokoro_speed ?? 1.0;
                } else if (_engine === 'piper') {
                  speed = ttsConfig.voice_speed ?? 1.0;
                } else if (_engine === 'espeak') {
                  voice = 'espeak';
                  speed = (ttsConfig.espeak_speed ?? 175) / 175;
                } else if (_engine === 'openai') {
                  speed = ttsConfig.openai_speed ?? 1.0;
                } else if (_engine === 'cartesia') {
                  voice = ttsConfig.cartesia_voice_id ?? '';
                  speed = ttsConfig.cartesia_speed ?? 1.0;
                }

                previewMutation.mutate({
                  persona: activeName,
                  message: text,
                  voice,
                  provider: _engine,
                  speed,
                });
              }}
              className={cn(
                'flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-all',
                'active:scale-[0.98] focus:outline-none focus:ring-2 focus:ring-blue-500',
                previewMutation.isSuccess
                  ? 'border border-green-400 bg-green-50 text-green-700 hover:bg-green-100 dark:border-green-700/60 dark:bg-green-950/20 dark:text-green-300 dark:hover:bg-green-950/30'
                  : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700',
              )}
            >
              <Volume2 className="h-4 w-4" />
              {previewMutation.isSuccess ? 'Preview Again' : 'Preview Voice'}
            </button>
          )}
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
