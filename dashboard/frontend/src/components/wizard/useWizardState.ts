/**
 * useWizardState — reducer-backed state management for CameraSetupWizard.
 *
 * Keeps all mutable wizard data in one place so the CameraSetupWizard
 * component stays declarative. Each dispatched action drives a deterministic
 * state transition — makes the flow easy to unit-test and reason about.
 *
 * State transitions:
 *   SELECT_CAMERA    → step: analysis
 *   ANALYSIS_COMPLETE → step: test  (sets streamName, detectResult, selectedCodec)
 *   TEST_HEARD       → step: success
 *   TEST_FAILED      → step: retry  (increments retryAttempt)
 *   TEST_PARTIAL     → step: retry  (increments retryAttempt)
 *   RETRY_HEARD      → step: success
 *   RETRY_FAILED     → step: retry  (increments retryAttempt)
 *   SET_SCENE_CONTEXT → updates sceneContext in-place (no step change)
 *   GO_TO_STEP       → jump to any step directly (used by Back button)
 *   RESET            → return to initial state (for "Set Up Another Camera")
 */

import { useReducer } from 'react';
import type { WizardStep, WizardState } from './CameraSetupWizard';
import type { DetectResponse, WizardTestResponse } from '@/api/wizard';

// ---------------------------------------------------------------------------
// Action union
// ---------------------------------------------------------------------------

type WizardAction =
  | { type: 'SELECT_CAMERA'; cameraName: string }
  | { type: 'ANALYSIS_COMPLETE'; result: DetectResponse }
  | { type: 'TEST_HEARD'; result: WizardTestResponse }
  | { type: 'TEST_FAILED'; result: WizardTestResponse }
  | { type: 'TEST_PARTIAL'; result: WizardTestResponse }
  | { type: 'RETRY_HEARD'; codec: string; result: WizardTestResponse }
  | { type: 'RETRY_FAILED'; codec: string; result: WizardTestResponse }
  | { type: 'SET_SCENE_CONTEXT'; value: string }
  | { type: 'GO_TO_STEP'; step: WizardStep }
  | { type: 'RESET' };

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

const initialState: WizardState = {
  step: 'select',
  cameraName: null,
  streamName: null,
  detectResult: null,
  selectedCodec: null,
  warmupDelay: 2,
  testResult: null,
  retryAttempt: 0,
  sceneContext: '',
};

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

/**
 * Pure reducer for wizard state transitions.
 * Each case documents which step it transitions to for quick orientation.
 */
function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    // Step 1 → 2: user selected a camera from the grid
    case 'SELECT_CAMERA':
      return {
        ...state,
        step: 'analysis',
        cameraName: action.cameraName,
        // Reset downstream state in case user returns to pick a different camera
        streamName: null,
        detectResult: null,
        selectedCodec: null,
        testResult: null,
        retryAttempt: 0,
      };

    // Step 2 → 3: detect probe completed successfully
    case 'ANALYSIS_COMPLETE': {
      const result = action.result;
      return {
        ...state,
        step: 'test',
        streamName: result.stream_name,
        detectResult: result,
        // Start with the backend's recommended codec; fall back to first in list
        selectedCodec:
          result.recommended_codec ??
          // codecs[0] is always a string here — length > 0 is checked above,
          // but noUncheckedIndexedAccess requires the assertion.
          (result.codecs.length > 0 ? normaliseCodec(result.codecs[0]!) : 'pcm_mulaw'),
        testResult: null,
        retryAttempt: 0,
      };
    }

    // Step 3 → 4: operator confirmed they heard audio
    case 'TEST_HEARD':
      return {
        ...state,
        step: 'success',
        testResult: action.result,
      };

    // Step 3 → 5: no audio heard, start retry flow
    case 'TEST_FAILED':
    case 'TEST_PARTIAL':
      return {
        ...state,
        step: 'retry',
        testResult: action.result,
        retryAttempt: state.retryAttempt + 1,
        // Advance to the next available codec for the first retry attempt
        selectedCodec: nextCodec(state),
      };

    // Retry step: operator confirmed a retry attempt worked
    case 'RETRY_HEARD':
      return {
        ...state,
        step: 'success',
        selectedCodec: action.codec,
        testResult: action.result,
      };

    // Retry step: another retry failed, stay on retry and try next codec
    case 'RETRY_FAILED':
      return {
        ...state,
        step: 'retry',
        selectedCodec: action.codec,
        testResult: action.result,
        retryAttempt: state.retryAttempt + 1,
      };

    // Configure step: update scene context without changing the step
    case 'SET_SCENE_CONTEXT':
      return { ...state, sceneContext: action.value };

    // Generic step jump (Back button, Skip link)
    case 'GO_TO_STEP':
      return { ...state, step: action.step };

    // Full reset for "Set Up Another Camera"
    case 'RESET':
      return { ...initialState };

    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * All codecs the wizard knows how to try, in preference order.
 * The backend may return codecs in a different order; this list is the
 * fallback cycling sequence used during retries.
 */
const CODEC_CYCLE = ['pcm_mulaw', 'pcm_alaw', 'aac', 'opus'];

/**
 * Normalise a raw go2rtc codec string (e.g. "PCMU/8000") into the short
 * codec key used by the VoxWatch backend (e.g. "pcm_mulaw").
 */
function normaliseCodec(raw: string): string {
  const upper = raw.toUpperCase();
  if (upper.startsWith('PCMU')) return 'pcm_mulaw';
  if (upper.startsWith('PCMA')) return 'pcm_alaw';
  if (upper.startsWith('AAC')) return 'aac';
  if (upper.startsWith('OPUS')) return 'opus';
  // Return the raw value lowercased if we don't recognise it
  return raw.toLowerCase();
}

/**
 * Pick the next codec to try during a retry.
 * Cycles through CODEC_CYCLE, preferring codecs reported by the detect
 * probe that haven't been tried yet before falling back to the full list.
 */
function nextCodec(state: WizardState): string {
  const available =
    state.detectResult?.codecs.map(normaliseCodec) ?? [];

  // Build the order to try: detected codecs first, then the full cycle list
  const candidates = [
    ...available,
    ...CODEC_CYCLE.filter((c) => !available.includes(c)),
  ];

  const currentIndex = candidates.indexOf(state.selectedCodec ?? '');
  const next = candidates[(currentIndex + 1) % candidates.length];
  return next ?? 'pcm_mulaw';
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Hook that provides the wizard reducer state and a typed dispatch function.
 *
 * @returns state — current WizardState
 * @returns dispatch — dispatch a WizardAction
 */
export function useWizardState(): {
  state: WizardState;
  dispatch: React.Dispatch<WizardAction>;
} {
  const [state, dispatch] = useReducer(wizardReducer, initialState);
  return { state, dispatch };
}
