/**
 * CameraSetupWizard — guided 6-step flow for enrolling a camera in VoxWatch.
 *
 * Steps:
 *   1. select   — choose a camera from the grid
 *   2. analysis — probe go2rtc for backchannel / codec info
 *   3. test     — push a live test tone, confirm audible output
 *   4. success  — show what worked (codec, latency), gate on Configure
 *   5. retry    — cycle codecs / settings when audio fails
 *   6. configure — fill in scene context and save config
 *   7. verify   — run a final push with saved settings, then Finish
 *
 * The `?camera=` query param can pre-select a camera name and jump straight
 * to the analysis step, making it easy to link from the Cameras page.
 *
 * State lives entirely inside this component — child step components receive
 * only the props they need, so each step is independently testable.
 */

import { useEffect, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { ChevronLeft, Wand2 } from 'lucide-react';
import { cn } from '@/utils/cn';
import type { DetectResponse, WizardTestResponse } from '@/api/wizard';
import {
  WizardStepCamera,
  WizardStepAnalysis,
  WizardStepTest,
  WizardStepSuccess,
  WizardStepRetry,
  WizardStepConfigure,
  WizardStepVerify,
} from './steps';
import { useWizardState } from './useWizardState';

// ---------------------------------------------------------------------------
// Step metadata
// ---------------------------------------------------------------------------

/**
 * All wizard steps in order.
 * 'retry' sits between 'test' and 'success' so it is not counted in the
 * linear progress bar — it is a conditional branch, not a numbered step.
 */
export type WizardStep =
  | 'select'
  | 'analysis'
  | 'test'
  | 'success'
  | 'retry'
  | 'configure'
  | 'verify';

/** Numbered steps shown in the progress indicator (retry is a branch, not numbered). */
const NUMBERED_STEPS: WizardStep[] = [
  'select',
  'analysis',
  'test',
  'configure',
  'verify',
];

/** Human-readable label for each numbered step. */
const STEP_LABELS: Record<string, string> = {
  select: 'Camera',
  analysis: 'Analyze',
  test: 'Test',
  configure: 'Configure',
  verify: 'Verify',
};

// ---------------------------------------------------------------------------
// WizardState type (exported so step components can consume it via props)
// ---------------------------------------------------------------------------

/** Complete wizard state passed down to each step component. */
export interface WizardState {
  step: WizardStep;
  /** Selected camera name. Null until the user picks one on step 1. */
  cameraName: string | null;
  /** go2rtc stream name resolved during analysis. */
  streamName: string | null;
  /** Full result from the /wizard/detect call. */
  detectResult: DetectResponse | null;
  /** Codec the current test is using (may differ from recommended after retries). */
  selectedCodec: string | null;
  /** Seconds to wait before sending audio (1–5). */
  warmupDelay: number;
  /** Result of the most recent /wizard/test-audio call. */
  testResult: WizardTestResponse | null;
  /** Number of auto-retry attempts so far (0 = first test). */
  retryAttempt: number;
  /** Operator-provided scene description for the AI context field. */
  sceneContext: string;
}

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

/**
 * Maps a WizardStep to its position in the NUMBERED_STEPS list (1-based).
 * 'success' and 'retry' are treated as part of the 'test' step visually.
 */
function stepIndex(step: WizardStep): number {
  if (step === 'success' || step === 'retry') {
    return NUMBERED_STEPS.indexOf('test') + 1;
  }
  const idx = NUMBERED_STEPS.indexOf(step);
  return idx === -1 ? 1 : idx + 1;
}

interface StepIndicatorProps {
  currentStep: WizardStep;
}

/**
 * Horizontal progress bar with numbered circles connected by lines.
 * On mobile the circles shrink to small dots and labels are hidden.
 */
function StepIndicator({ currentStep }: StepIndicatorProps) {
  const active = stepIndex(currentStep);

  return (
    <nav aria-label="Wizard progress" className="mb-6">
      {/* Desktop: numbered circles with labels */}
      <ol className="hidden sm:flex items-center">
        {NUMBERED_STEPS.map((step, i) => {
          const num = i + 1;
          const isDone = num < active;
          const isCurrent = num === active;

          return (
            <li key={step} className="flex items-center flex-1 last:flex-none">
              {/* Circle */}
              <div className="flex flex-col items-center">
                <div
                  className={cn(
                    'flex h-8 w-8 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors',
                    isDone
                      ? 'border-blue-600 bg-blue-600 text-white'
                      : isCurrent
                        ? 'border-blue-600 bg-white text-blue-600 dark:bg-gray-900 dark:text-blue-400'
                        : 'border-gray-300 bg-white text-gray-400 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-500',
                  )}
                  aria-current={isCurrent ? 'step' : undefined}
                >
                  {isDone ? (
                    // Checkmark for completed steps
                    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 00-1.414 0L8 12.586 4.707 9.293a1 1 0 00-1.414 1.414l4 4a1 1 0 001.414 0l8-8a1 1 0 000-1.414z" clipRule="evenodd" />
                    </svg>
                  ) : (
                    num
                  )}
                </div>
                <span
                  className={cn(
                    'mt-1 text-xs font-medium',
                    isCurrent
                      ? 'text-blue-600 dark:text-blue-400'
                      : isDone
                        ? 'text-gray-500 dark:text-gray-400'
                        : 'text-gray-400 dark:text-gray-600',
                  )}
                >
                  {STEP_LABELS[step]}
                </span>
              </div>

              {/* Connecting line (not after the last step) */}
              {i < NUMBERED_STEPS.length - 1 && (
                <div
                  className={cn(
                    'mx-2 h-0.5 flex-1 transition-colors',
                    num < active
                      ? 'bg-blue-600'
                      : 'bg-gray-200 dark:bg-gray-700',
                  )}
                  aria-hidden="true"
                />
              )}
            </li>
          );
        })}
      </ol>

      {/* Mobile: small dot indicators only */}
      <ol className="flex sm:hidden items-center justify-center gap-2" aria-hidden="true">
        {NUMBERED_STEPS.map((step, i) => {
          const num = i + 1;
          const isDone = num < active;
          const isCurrent = num === active;
          return (
            <li key={step}>
              <div
                className={cn(
                  'h-2 w-2 rounded-full transition-colors',
                  isDone
                    ? 'bg-blue-600'
                    : isCurrent
                      ? 'bg-blue-400 ring-2 ring-blue-400 ring-offset-2 ring-offset-white dark:ring-offset-gray-900'
                      : 'bg-gray-300 dark:bg-gray-600',
                )}
              />
            </li>
          );
        })}
      </ol>

      {/* Mobile: current step label */}
      <p className="mt-2 text-center text-xs font-medium text-blue-600 dark:text-blue-400 sm:hidden">
        Step {active} of {NUMBERED_STEPS.length} — {STEP_LABELS[NUMBERED_STEPS[active - 1] ?? 'select']}
      </p>
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Back button
// ---------------------------------------------------------------------------

/** Determines which step the Back button should navigate to from a given step. */
function backTarget(step: WizardStep): WizardStep | null {
  const map: Partial<Record<WizardStep, WizardStep>> = {
    analysis: 'select',
    test: 'analysis',
    success: 'test',
    retry: 'test',
    configure: 'success',
    verify: 'configure',
  };
  return map[step] ?? null;
}

// ---------------------------------------------------------------------------
// Main wizard component
// ---------------------------------------------------------------------------

/**
 * Full-page guided wizard for adding a camera to VoxWatch.
 *
 * Reads `?camera=` from the URL on mount. If present the wizard skips the
 * select step and fires the analysis probe immediately.
 *
 * @example
 *   // From the cameras page:
 *   navigate('/wizard?camera=frontdoor')
 */
export function CameraSetupWizard() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { state, dispatch } = useWizardState();

  // Read ?camera= query param and auto-advance past the select step
  useEffect(() => {
    const cam = searchParams.get('camera');
    if (cam && state.step === 'select') {
      dispatch({ type: 'SELECT_CAMERA', cameraName: cam });
    }
    // Only run once on mount — intentionally omitting state.step and dispatch
    // from deps to avoid re-triggering if they change later.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Navigate to the previous logical step. */
  const handleBack = useCallback(() => {
    const target = backTarget(state.step);
    if (target) {
      dispatch({ type: 'GO_TO_STEP', step: target });
    }
  }, [state.step, dispatch]);

  const back = backTarget(state.step);

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      {/* Page heading */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600 text-white">
          <Wand2 className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-lg font-bold text-gray-900 dark:text-gray-100">
            Camera Setup Wizard
          </h1>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Walk through detection, audio test, and configuration in minutes.
          </p>
        </div>
      </div>

      {/* Step progress bar */}
      <StepIndicator currentStep={state.step} />

      {/* Back navigation */}
      {back && (
        <button
          onClick={handleBack}
          className={cn(
            'flex items-center gap-1.5 text-sm font-medium transition-colors',
            'text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100',
            'focus:outline-none focus:ring-2 focus:ring-blue-500 rounded',
          )}
        >
          <ChevronLeft className="h-4 w-4" />
          Back
        </button>
      )}

      {/* Active step */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-card dark:border-gray-700/50 dark:bg-gray-900">
        {state.step === 'select' && (
          <WizardStepCamera
            onSelect={(name) => dispatch({ type: 'SELECT_CAMERA', cameraName: name })}
          />
        )}

        {state.step === 'analysis' && state.cameraName && (
          <WizardStepAnalysis
            cameraName={state.cameraName}
            onComplete={(result) => dispatch({ type: 'ANALYSIS_COMPLETE', result })}
            onError={() => dispatch({ type: 'GO_TO_STEP', step: 'select' })}
          />
        )}

        {state.step === 'test' && state.cameraName && state.streamName && state.selectedCodec && (
          <WizardStepTest
            cameraName={state.cameraName}
            streamName={state.streamName}
            codec={state.selectedCodec}
            warmupDelay={state.warmupDelay}
            onHeard={(result) => dispatch({ type: 'TEST_HEARD', result })}
            onNoAudio={(result) => dispatch({ type: 'TEST_FAILED', result })}
            onPartial={(result) => dispatch({ type: 'TEST_PARTIAL', result })}
          />
        )}

        {state.step === 'success' && state.cameraName && state.streamName && state.selectedCodec && state.testResult && (
          <WizardStepSuccess
            cameraName={state.cameraName}
            streamName={state.streamName}
            codec={state.selectedCodec}
            warmupDelay={state.warmupDelay}
            testResult={state.testResult}
            onContinue={() => dispatch({ type: 'GO_TO_STEP', step: 'configure' })}
          />
        )}

        {state.step === 'retry' && state.cameraName && state.streamName && (
          <WizardStepRetry
            cameraName={state.cameraName}
            streamName={state.streamName}
            detectResult={state.detectResult}
            retryAttempt={state.retryAttempt}
            warmupDelay={state.warmupDelay}
            onHeard={(codec, result) =>
              dispatch({ type: 'RETRY_HEARD', codec, result })
            }
            onNoAudio={(codec, result) =>
              dispatch({ type: 'RETRY_FAILED', codec, result })
            }
            onSkip={() => dispatch({ type: 'GO_TO_STEP', step: 'configure' })}
          />
        )}

        {state.step === 'configure' && state.cameraName && state.streamName && (
          <WizardStepConfigure
            cameraName={state.cameraName}
            streamName={state.streamName}
            selectedCodec={state.selectedCodec}
            sceneContext={state.sceneContext}
            onSceneContextChange={(v) =>
              dispatch({ type: 'SET_SCENE_CONTEXT', value: v })
            }
            onSaved={() => dispatch({ type: 'GO_TO_STEP', step: 'verify' })}
          />
        )}

        {state.step === 'verify' && state.cameraName && state.streamName && (
          <WizardStepVerify
            cameraName={state.cameraName}
            streamName={state.streamName}
            codec={state.selectedCodec}
            warmupDelay={state.warmupDelay}
            onFinish={() => navigate('/cameras')}
            onSetupAnother={() => dispatch({ type: 'RESET' })}
          />
        )}
      </div>
    </div>
  );
}
