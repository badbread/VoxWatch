/**
 * StagesConfigForm — visual pipeline builder for the three deterrent stages.
 *
 * Pipeline:
 *   1. Initial Response  — plays immediately on detection, no AI needed.
 *   2. Escalation        — AI-powered response, fires after a delay if person
 *                          is still present. Combines snapshot + video settings.
 *   3. Resolution        — optional "all clear" message when person leaves.
 *
 * The form writes to:
 *   - `pipeline.initial_response` / `pipeline.escalation` / `pipeline.resolution`
 *     (new flat structure read by the backend)
 *   - `stage2` / `stage3` (legacy keys still read by the backend for snapshot
 *     and video-clip parameters — kept for backward compatibility)
 *   - `messages.stageN_tone` (legacy tone keys read by `_get_stage_tone()`)
 */

import { useState } from 'react';
import {
  Zap,
  TrendingUp,
  RefreshCw,
  CheckCircle,
  ArrowRight,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { inputCls, Field } from '@/components/common/FormField';
import type {
  PipelineConfig,
  PipelineInitialResponse,
  PipelineEscalation,
  PipelineResolution,
  Stage2Config,
  Stage3Config,
  MessagesConfig,
  ConfigValidationError,
} from '@/types/config';

// ---------------------------------------------------------------------------
// Tone selector
// ---------------------------------------------------------------------------

/** Canonical tone values understood by the backend. */
const TONE_OPTIONS: { value: string; label: string }[] = [
  { value: 'none',   label: 'None' },
  { value: 'short',  label: 'Short Beep (150 ms)' },
  { value: 'siren',  label: 'Siren (rising sweep)' },
  { value: 'long',   label: 'Long Alert (two-tone)' },
  { value: 'custom', label: 'Custom WAV path...' },
];

interface ToneSelectorProps {
  /** Current dropdown value: "none" | "short" | "siren" | "long" | "custom". */
  tone: string;
  /** Current custom WAV path (only shown when tone === "custom"). */
  customPath: string;
  onToneChange: (tone: string) => void;
  onCustomPathChange: (path: string) => void;
}

/**
 * Dropdown + optional path input for selecting an attention tone.
 * The tone is prepended to the TTS audio in a single combined push.
 */
function ToneSelector({ tone, customPath, onToneChange, onCustomPathChange }: ToneSelectorProps) {
  return (
    <div className="space-y-2">
      <Field
        label="Attention Tone"
        hint="Plays before the voice message. Combined into a single audio push."
      >
        <select
          value={tone}
          onChange={(e) => onToneChange(e.target.value)}
          className={inputCls(false)}
        >
          {TONE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </Field>

      {tone === 'custom' && (
        <Field
          label="Custom WAV Path"
          hint="Absolute path to a WAV file on the container filesystem (e.g. /data/my_tone.wav)."
        >
          <input
            type="text"
            value={customPath}
            onChange={(e) => onCustomPathChange(e.target.value)}
            className={inputCls(false)}
            placeholder="/data/my_tone.wav"
          />
        </Field>
      )}
    </div>
  );
}

/**
 * Derive the dropdown selection from a raw attention_tone value, which may be
 * a file path rather than a recognised keyword.
 */
function toneDropdownValue(raw: string | undefined): string {
  if (!raw || raw === 'none') return 'none';
  const known = ['short', 'siren', 'long'];
  if (known.includes(raw)) return raw;
  return 'custom';
}

/**
 * The actual value to persist: for "custom" selections use the custom path
 * directly (the backend treats any unrecognised string as a file path).
 */
function resolvedToneValue(dropdownValue: string, customPath: string): string {
  if (dropdownValue === 'custom') return customPath || 'none';
  return dropdownValue;
}

// ---------------------------------------------------------------------------
// Stage enable toggle
// ---------------------------------------------------------------------------

interface StageToggleProps {
  enabled: boolean;
  label: string;
  onChange: (enabled: boolean) => void;
}

function StageToggle({ enabled, label, onChange }: StageToggleProps) {
  return (
    <div
      className={cn(
        'relative h-5 w-9 cursor-pointer rounded-full transition-colors',
        'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1',
        enabled ? 'bg-blue-600' : 'bg-gray-300 dark:bg-gray-600',
      )}
      onClick={() => onChange(!enabled)}
      onKeyDown={(e) => {
        if (e.key === ' ' || e.key === 'Enter') {
          e.preventDefault();
          onChange(!enabled);
        }
      }}
      role="switch"
      tabIndex={0}
      aria-checked={enabled}
      aria-label={`${enabled ? 'Disable' : 'Enable'} ${label}`}
    >
      <div
        className={cn(
          'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
          enabled ? 'translate-x-4' : 'translate-x-0.5',
        )}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Default stage values
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Stage card — defined outside StagesConfigForm to prevent re-mount on
// every state change (which would steal input focus)
// ---------------------------------------------------------------------------

interface StageCardProps {
  id: string;
  label: string;
  description: string;
  icon: typeof Zap;
  iconColor: string;
  enabled: boolean;
  expanded: boolean;
  onToggle: (enabled: boolean) => void;
  onExpand: (id: string | null) => void;
  children: React.ReactNode;
}

function StageCard({ id, label, description, icon: Icon, iconColor, enabled, expanded, onToggle, onExpand, children }: StageCardProps) {
  return (
    <div
      className={cn(
        'rounded-2xl border transition-all duration-200',
        enabled
          ? 'border-gray-200 bg-white hover:border-gray-300 dark:border-gray-700/50 dark:bg-gray-900/60 dark:hover:border-gray-600/60'
          : 'border-gray-200 bg-gray-50 opacity-50 dark:border-gray-800/40 dark:bg-gray-900/30',
      )}
    >
      <div className="flex items-center gap-3 px-4 py-3.5">
        <Icon className={cn('h-5 w-5 flex-shrink-0', iconColor)} />
        <button
          onClick={() => onExpand(expanded ? null : id)}
          className="flex-1 min-w-0 text-left"
        >
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{label}</p>
          <p className="text-xs text-gray-500 dark:text-gray-500">{description}</p>
        </button>
        <StageToggle enabled={enabled} label={label} onChange={onToggle} />
      </div>
      {expanded && enabled && (
        <div className="border-t border-gray-200 dark:border-gray-700/40 px-4 py-4">
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Default stage values
// ---------------------------------------------------------------------------

const DEFAULT_INITIAL_RESPONSE: PipelineInitialResponse = {
  enabled: true,
  delay: 0,
  message: '',
};

const DEFAULT_ESCALATION: PipelineEscalation = {
  enabled: true,
  delay: 6,
  condition: 'person_still_present',
};

const DEFAULT_RESOLUTION: PipelineResolution = {
  enabled: false,
  message: 'Area clear.',
};

// ---------------------------------------------------------------------------
// Component props
// ---------------------------------------------------------------------------

export interface StagesConfigFormProps {
  stage2: Stage2Config;
  stage3: Stage3Config;
  messages?: MessagesConfig | undefined;
  pipeline?: PipelineConfig | undefined;
  onStage2Change: (v: Stage2Config) => void;
  onStage3Change: (v: Stage3Config) => void;
  onMessagesChange?: (v: MessagesConfig) => void;
  onPipelineChange?: (v: PipelineConfig) => void;
  errors: ConfigValidationError[];
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * Three-stage pipeline builder: Initial Response, Escalation, Resolution.
 */
export function StagesConfigForm({
  stage2,
  stage3,
  messages,
  pipeline,
  onStage2Change,
  onStage3Change,
  onMessagesChange,
  onPipelineChange,
}: StagesConfigFormProps) {
  const [expandedStage, setExpandedStage] = useState<string | null>(null);

  // Resolve current stage values from pipeline config, falling back to defaults.
  const initialResponse: PipelineInitialResponse = pipeline?.initial_response ?? DEFAULT_INITIAL_RESPONSE;
  const escalation: PipelineEscalation = pipeline?.escalation ?? DEFAULT_ESCALATION;
  const resolution: PipelineResolution = pipeline?.resolution ?? DEFAULT_RESOLUTION;

  const defaultMessages: MessagesConfig = messages ?? {
    stage1: 'Attention. You are on private property and are being recorded.',
    stage2_prefix: '',
    stage2_suffix: '',
    stage3_prefix: '',
    stage3_suffix: '',
  };

  // ── Pipeline change helpers ──────────────────────────────────────────────

  const updatePipeline = (patch: Partial<PipelineConfig>) => {
    onPipelineChange?.({ ...pipeline, ...patch });
  };

  const updateInitialResponse = (patch: Partial<PipelineInitialResponse>) => {
    const updated = { ...initialResponse, ...patch };
    updatePipeline({ initial_response: updated });

    // Mirror tone to legacy messages.stage1_tone for backend compatibility.
    if (('attention_tone' in patch || 'attention_tone_custom_path' in patch) && onMessagesChange) {
      const resolved = resolvedToneValue(
        toneDropdownValue(updated.attention_tone),
        updated.attention_tone_custom_path ?? '',
      );
      onMessagesChange({ ...defaultMessages, stage1_tone: resolved });
    }
  };

  const updateEscalation = (patch: Partial<PipelineEscalation>) => {
    const updated = { ...escalation, ...patch };
    updatePipeline({ escalation: updated });

    // Mirror tone to legacy messages.stage2_tone and stage3_tone.
    if (('attention_tone' in patch || 'attention_tone_custom_path' in patch) && onMessagesChange) {
      const resolved = resolvedToneValue(
        toneDropdownValue(updated.attention_tone),
        updated.attention_tone_custom_path ?? '',
      );
      onMessagesChange({
        ...defaultMessages,
        stage2_tone: resolved,
        stage3_tone: resolved,
      });
    }
  };

  const updatePersistentDeterrence = (patch: Record<string, unknown>) => {
    updatePipeline({ persistent_deterrence: { ...persistentDeterrence, ...patch } });
  };

  const updateResolution = (patch: Partial<PipelineResolution>) => {
    updatePipeline({ resolution: { ...resolution, ...patch } });
  };

  // ── Active pipeline stages for the flow preview ──────────────────────────

  const activeStagePills: { label: string; color: string }[] = [];
  if (initialResponse.enabled) {
    activeStagePills.push({ label: 'Initial Response', color: 'bg-yellow-100 text-yellow-700 border-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400 dark:border-yellow-800/40' });
  }
  if (escalation.enabled) {
    activeStagePills.push({ label: 'Escalation', color: 'bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800/40' });
  }
  const persistentDeterrence = pipeline?.persistent_deterrence ?? { enabled: false, delay_seconds: 30, max_iterations: 5, alarm_tone: 'none', describe_actions: true, escalation_tone: 'increasing' };
  if (persistentDeterrence.enabled) {
    activeStagePills.push({ label: 'Persistent Deterrence', color: 'bg-orange-100 text-orange-700 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800/40' });
  }
  if (resolution.enabled) {
    activeStagePills.push({ label: 'Resolution', color: 'bg-green-100 text-green-700 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800/40' });
  }

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">
      <p className="text-sm text-gray-500">
        Stages fire in sequence on detection. Enable or disable each stage, then click to expand settings.
      </p>

      {/* Active pipeline flow preview */}
      <div className="rounded-2xl border border-gray-200 bg-gray-50 dark:border-gray-700/40 dark:bg-gray-900/60 px-5 py-4">
        <span className="text-xs font-semibold uppercase tracking-widest text-gray-500 dark:text-gray-500">
          Active Pipeline
        </span>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="rounded-xl bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 px-3 py-1 text-xs font-semibold border border-red-200 dark:border-red-800/40">
            Person Detected
          </span>
          {activeStagePills.length === 0 ? (
            <>
              <ArrowRight className="h-3.5 w-3.5 text-gray-400 dark:text-gray-600" />
              <span className="text-xs text-gray-400 dark:text-gray-500 italic">No stages enabled</span>
            </>
          ) : (
            activeStagePills.map((pill) => (
              <div key={pill.label} className="flex items-center gap-2">
                <ArrowRight className="h-3.5 w-3.5 text-gray-400 dark:text-gray-600" />
                <span className={cn('rounded-xl px-3 py-1 text-xs font-semibold border', pill.color)}>
                  {pill.label}
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Stage cards */}
      <div className="space-y-2">

        {/* 1. Initial Response */}
        <StageCard
          id="initial_response"
          label="1. Initial Response"
          description="Plays immediately on detection. Short, direct, mode-specific message."
          icon={Zap}
          iconColor="text-yellow-500"
          enabled={initialResponse.enabled}
          expanded={expandedStage === "initial_response"}
          onExpand={setExpandedStage}
          onToggle={(enabled) => updateInitialResponse({ enabled })}
        >
          <div className="space-y-3">
            <p className="text-xs text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 rounded px-3 py-2">
              Uses your Personality's default message. AI description is NOT needed for this stage.
            </p>

            <Field
              label="Delay (seconds)"
              hint="How long to wait before playing after detection. Usually 0 for immediate playback."
            >
              <input
                type="number"
                min={0}
                max={30}
                step={0.5}
                value={initialResponse.delay}
                onChange={(e) => updateInitialResponse({ delay: Number(e.target.value) })}
                className={inputCls(false)}
              />
            </Field>

            <Field
              label="Message Override (optional)"
              hint="Leave blank to use the Personality's default message."
            >
              <textarea
                value={initialResponse.message ?? ''}
                onChange={(e) => updateInitialResponse({ message: e.target.value })}
                rows={2}
                className={cn(inputCls(false), 'resize-y')}
                placeholder="Leave blank to use personality default..."
              />
            </Field>

            <ToneSelector
              tone={toneDropdownValue(initialResponse.attention_tone)}
              customPath={initialResponse.attention_tone_custom_path ?? ''}
              onToneChange={(t) => updateInitialResponse({ attention_tone: t })}
              onCustomPathChange={(p) => updateInitialResponse({ attention_tone_custom_path: p })}
            />
          </div>
        </StageCard>

        {/* 2. Escalation */}
        <StageCard
          id="escalation"
          label="2. Escalation"
          description="AI-powered response. Only fires if person is still present after Initial Response."
          icon={TrendingUp}
          iconColor="text-blue-500"
          enabled={escalation.enabled}
          expanded={expandedStage === "escalation"}
          onExpand={setExpandedStage}
          onToggle={(enabled) => updateEscalation({ enabled })}
        >
          <div className="space-y-3">
            <p className="text-xs text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 rounded px-3 py-2">
              AI analyzes camera snapshots and describes the person. For dispatch modes, includes radio effects.
            </p>

            {/* Delay + condition */}
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Delay after Initial Response (seconds)"
                hint="How long to wait before the AI response fires (default 6s)."
              >
                <input
                  type="number"
                  min={0}
                  max={60}
                  step={0.5}
                  value={escalation.delay}
                  onChange={(e) => updateEscalation({ delay: Number(e.target.value) })}
                  className={inputCls(false)}
                />
              </Field>
            </div>

            <div className="space-y-1.5">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                <input
                  type="checkbox"
                  checked={escalation.condition === 'person_still_present'}
                  onChange={(e) =>
                    updateEscalation({ condition: e.target.checked ? 'person_still_present' : 'always' })
                  }
                  className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600"
                />
                Only fire if person is still present
              </label>
            </div>

            {/* Snapshot settings (writes to stage2) */}
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                Snapshot Settings
              </p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Snapshot Count">
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={stage2.snapshot_count}
                    onChange={(e) => onStage2Change({ ...stage2, snapshot_count: Number(e.target.value) })}
                    className={inputCls(false)}
                  />
                </Field>
                <Field label="Interval (ms)">
                  <input
                    type="number"
                    min={100}
                    max={5000}
                    step={100}
                    value={stage2.snapshot_interval_ms}
                    onChange={(e) => onStage2Change({ ...stage2, snapshot_interval_ms: Number(e.target.value) })}
                    className={inputCls(false)}
                  />
                </Field>
              </div>
            </div>

            {/* Video clip settings (writes to stage3) */}
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                Video Clip Settings
              </p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Video Clip Length (seconds)">
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={stage3.video_clip_seconds}
                    onChange={(e) => onStage3Change({ ...stage3, video_clip_seconds: Number(e.target.value) })}
                    className={inputCls(false)}
                  />
                </Field>
                <Field label="Fallback Snapshot Count">
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={stage3.fallback_snapshot_count}
                    onChange={(e) => onStage3Change({ ...stage3, fallback_snapshot_count: Number(e.target.value) })}
                    className={inputCls(false)}
                  />
                </Field>
              </div>
              <div className="mt-2 space-y-1.5">
                <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                  <input
                    type="checkbox"
                    checked={stage3.fallback_to_snapshots}
                    onChange={(e) => onStage3Change({ ...stage3, fallback_to_snapshots: e.target.checked })}
                    className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600"
                  />
                  Fall back to snapshots if video unavailable
                </label>
              </div>
            </div>

            {/* Prefix / suffix (writes to messages.stage2_* and stage3_*) */}
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                Message Wrappers
              </p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Prefix (before AI description)">
                  <input
                    type="text"
                    value={defaultMessages.stage2_prefix}
                    onChange={(e) =>
                      onMessagesChange?.({
                        ...defaultMessages,
                        stage2_prefix: e.target.value,
                        stage3_prefix: e.target.value,
                      })
                    }
                    className={inputCls(false)}
                    placeholder="Optional — personality handles this by default"
                  />
                </Field>
                <Field label="Suffix (after AI description)">
                  <input
                    type="text"
                    value={defaultMessages.stage2_suffix}
                    onChange={(e) =>
                      onMessagesChange?.({
                        ...defaultMessages,
                        stage2_suffix: e.target.value,
                        stage3_suffix: e.target.value,
                      })
                    }
                    className={inputCls(false)}
                    placeholder="Optional — personality handles this by default"
                  />
                </Field>
              </div>
            </div>

            <ToneSelector
              tone={toneDropdownValue(escalation.attention_tone)}
              customPath={escalation.attention_tone_custom_path ?? ''}
              onToneChange={(t) => updateEscalation({ attention_tone: t })}
              onCustomPathChange={(p) => updateEscalation({ attention_tone_custom_path: p })}
            />
          </div>
        </StageCard>

        {/* 3. Persistent Deterrence */}
        <StageCard
          id="persistent_deterrence"
          label="3. Persistent Deterrence"
          description="If person stays after escalation, keeps warning them with fresh AI descriptions every N seconds."
          icon={RefreshCw}
          iconColor="text-orange-500"
          enabled={persistentDeterrence.enabled}
          expanded={expandedStage === "persistent_deterrence"}
          onExpand={setExpandedStage}
          onToggle={(enabled) => updatePersistentDeterrence({ enabled })}
        >
          <div className="space-y-3">
            <p className="text-xs text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/20 rounded px-3 py-2">
              After the Escalation stage completes, VoxWatch waits the configured delay, then checks if the person is still present. If yes, it generates a fresh AI description of their current actions and pushes another warning. This repeats until the person leaves or the max iteration count is reached.
            </p>

            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Delay Between Warnings (seconds)"
                hint="How long to wait after escalation (and between each loop iteration) before the next warning. The first persistent deterrence warning fires this many seconds after the escalation stage completes."
              >
                <input
                  type="number"
                  min={10}
                  max={120}
                  step={5}
                  value={persistentDeterrence.delay_seconds ?? 30}
                  onChange={(e) => updatePersistentDeterrence({ delay_seconds: Number(e.target.value) })}
                  className={inputCls(false)}
                />
              </Field>

              <Field
                label="Max Iterations"
                hint="Safety cap to prevent runaway AI costs."
              >
                <input
                  type="number"
                  min={1}
                  max={20}
                  step={1}
                  value={persistentDeterrence.max_iterations ?? 5}
                  onChange={(e) => updatePersistentDeterrence({ max_iterations: Number(e.target.value) })}
                  className={inputCls(false)}
                />
              </Field>
            </div>

            <div className="space-y-2">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                <input
                  type="checkbox"
                  checked={persistentDeterrence.describe_actions ?? true}
                  onChange={(e) => updatePersistentDeterrence({ describe_actions: e.target.checked })}
                  className="h-3.5 w-3.5 rounded border-gray-300 text-orange-600"
                />
                Generate fresh AI descriptions each loop
              </label>
              <p className="ml-6 text-xs text-gray-400">
                When disabled, uses a canned "you are still being monitored" message instead (no AI cost).
              </p>
            </div>

            <Field
              label="Tone Escalation"
              hint="How the message urgency changes across iterations."
            >
              <select
                value={persistentDeterrence.escalation_tone ?? 'increasing'}
                onChange={(e) => updatePersistentDeterrence({ escalation_tone: e.target.value })}
                className={inputCls(false)}
              >
                <option value="increasing">Increasing — gets more urgent each loop</option>
                <option value="steady">Steady — same tone throughout</option>
              </select>
            </Field>

            {(persistentDeterrence.escalation_tone ?? 'increasing') === 'increasing' && (
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                  Tone Levels
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  AI tone instructions for each escalation tier. Levels are distributed evenly across iterations.
                </p>
                {(persistentDeterrence.tone_levels ?? [
                  'Tone: firm and direct.',
                  'Tone: stern and urgent.',
                  'Tone: very serious, final warning energy.',
                ]).map((level: string, i: number) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="flex-shrink-0 text-xs font-medium text-gray-500 w-16">Level {i + 1}</span>
                    <input
                      type="text"
                      value={level}
                      onChange={(e) => {
                        const levels = [...(persistentDeterrence.tone_levels ?? [
                          'Tone: firm and direct.',
                          'Tone: stern and urgent.',
                          'Tone: very serious, final warning energy.',
                        ])];
                        levels[i] = e.target.value;
                        updatePersistentDeterrence({ tone_levels: levels });
                      }}
                      className={inputCls(false)}
                      placeholder={`Tone instruction for level ${i + 1}`}
                    />
                    {(persistentDeterrence.tone_levels ?? []).length > 1 && (
                      <button
                        type="button"
                        onClick={() => {
                          const levels = [...(persistentDeterrence.tone_levels ?? [])];
                          levels.splice(i, 1);
                          updatePersistentDeterrence({ tone_levels: levels });
                        }}
                        className="flex-shrink-0 text-xs text-red-400 hover:text-red-300"
                      >
                        remove
                      </button>
                    )}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => {
                    const levels = [...(persistentDeterrence.tone_levels ?? [])];
                    levels.push('Tone: ');
                    updatePersistentDeterrence({ tone_levels: levels });
                  }}
                  className="text-xs font-medium text-blue-500 hover:text-blue-400"
                >
                  + Add level
                </button>
              </div>
            )}

            <Field
              label="Alarm Tone"
              hint="Sound played before each deterrence message."
            >
              <select
                value={persistentDeterrence.alarm_tone ?? 'none'}
                onChange={(e) => updatePersistentDeterrence({ alarm_tone: e.target.value })}
                className={inputCls(false)}
              >
                <option value="none">None</option>
                <option value="brief">Brief beep before each message</option>
                <option value="continuous">Continuous alarm overlay</option>
              </select>
            </Field>
          </div>
        </StageCard>

        {/* 4. Resolution */}
        <StageCard
          id="resolution"
          label="4. Resolution"
          description="Optional message when the person leaves. Plays after last active stage."
          icon={CheckCircle}
          iconColor="text-green-500"
          enabled={resolution.enabled}
          expanded={expandedStage === "resolution"}
          onExpand={setExpandedStage}
          onToggle={(enabled) => updateResolution({ enabled })}
        >
          <div className="space-y-3">
            <Field label="Message">
              <textarea
                value={resolution.message}
                onChange={(e) => updateResolution({ message: e.target.value })}
                rows={2}
                className={cn(inputCls(false), 'resize-y')}
                placeholder="Area clear."
              />
            </Field>

            <ToneSelector
              tone={toneDropdownValue(resolution.attention_tone)}
              customPath={resolution.attention_tone_custom_path ?? ''}
              onToneChange={(t) => updateResolution({ attention_tone: t })}
              onCustomPathChange={(p) => updateResolution({ attention_tone_custom_path: p })}
            />
          </div>
        </StageCard>

      </div>
    </div>
  );
}
