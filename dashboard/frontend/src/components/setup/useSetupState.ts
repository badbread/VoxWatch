/**
 * useSetupState — reducer-backed state management for the first-run SetupWizard.
 *
 * All mutable wizard data lives here so SetupWizard stays declarative.
 * Step components receive only the slice of state they need, making each
 * independently testable.
 *
 * State transitions:
 *   SET_STEP           → navigate to any named step
 *   SET_FRIGATE        → update frigateHost / frigatePort
 *   SET_GO2RTC         → update go2rtcHost / go2rtcPort
 *   SET_MQTT           → update mqtt fields
 *   SET_PROBE_RESULT   → store ProbeResult after discovery
 *   SET_PROBING        → toggle probe loading indicator
 *   SET_AI             → update aiProvider / aiModel / aiApiKey / aiHost
 *   SET_TTS            → update ttsEngine / ttsVoice
 *   SET_RESPONSE_MODE  → update responseMode
 *   TOGGLE_CAMERA      → enable or disable a single camera
 *   SET_CAMERA_STREAM  → assign a go2rtc stream to a camera
 *   SET_GENERATING     → toggle config-generation loading indicator
 *   RESET              → return to initial state
 */

import { useReducer } from 'react';
import type { ProbeResult } from '@/api/setup';

// ---------------------------------------------------------------------------
// Step type
// ---------------------------------------------------------------------------

/**
 * All named steps of the first-run wizard in traversal order.
 * The progress bar renders them in this sequence.
 */
export type SetupStep =
  | 'welcome'
  | 'frigate'
  | 'discovery'
  | 'mqtt'
  | 'ai'
  | 'tts'
  | 'mode'
  | 'cameras'
  | 'review';

/** Ordered list used by the step indicator and back-navigation logic. */
export const SETUP_STEPS: SetupStep[] = [
  'welcome',
  'frigate',
  'discovery',
  'mqtt',
  'ai',
  'tts',
  'mode',
  'cameras',
  'review',
];

// ---------------------------------------------------------------------------
// State shape
// ---------------------------------------------------------------------------

/** Complete state managed by the setup wizard. */
export interface SetupState {
  /** Currently active step. */
  currentStep: SetupStep;

  // -- Frigate / go2rtc connection ------------------------------------------
  frigateHost: string;
  frigatePort: number;
  go2rtcHost: string;
  go2rtcPort: number;

  // -- MQTT ------------------------------------------------------------------
  mqttHost: string;
  mqttPort: number;
  mqttUser: string;
  mqttPassword: string;
  mqttTopic: string;

  // -- Discovery result ------------------------------------------------------
  /** Result from POST /api/setup/probe. Null until discovery runs. */
  probeResult: ProbeResult | null;
  /** Whether a probe request is in-flight. */
  isProbing: boolean;

  // -- AI provider -----------------------------------------------------------
  aiProvider: string;
  aiModel: string;
  aiApiKey: string;
  /** Host URL for self-hosted providers (Ollama, custom). */
  aiHost: string;

  // -- TTS -------------------------------------------------------------------
  ttsEngine: string;
  ttsVoice: string;

  // -- Response mode ---------------------------------------------------------
  responseMode: string;

  // -- Camera selection ------------------------------------------------------
  /**
   * Map of camera name → { enabled, go2rtc_stream, audio_codec }.
   * Populated once probeResult is available; the user toggles cameras on this step.
   */
  selectedCameras: Record<string, { enabled: boolean; go2rtc_stream: string; audio_codec?: string }>;

  // -- Submission state ------------------------------------------------------
  /** Whether a config-generation request is in-flight. */
  isGenerating: boolean;
}

// ---------------------------------------------------------------------------
// Action union
// ---------------------------------------------------------------------------

type SetupAction =
  | { type: 'SET_STEP'; step: SetupStep }
  | { type: 'SET_FRIGATE'; host: string; port: number }
  | { type: 'SET_GO2RTC'; host: string; port: number }
  | { type: 'SET_MQTT'; host: string; port: number; user: string; password: string; topic: string }
  | { type: 'SET_PROBE_RESULT'; result: ProbeResult }
  | { type: 'SET_PROBING'; value: boolean }
  | { type: 'SET_AI'; provider: string; model: string; apiKey: string; host: string }
  | { type: 'SET_TTS'; engine: string; voice: string }
  | { type: 'SET_RESPONSE_MODE'; mode: string }
  | { type: 'TOGGLE_CAMERA'; name: string; enabled: boolean }
  | { type: 'SET_CAMERA_STREAM'; name: string; stream: string }
  | { type: 'INIT_CAMERAS'; cameras: Record<string, { enabled: boolean; go2rtc_stream: string; audio_codec?: string }> }
  | { type: 'SET_GENERATING'; value: boolean }
  | { type: 'RESET' };

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

const initialState: SetupState = {
  currentStep: 'welcome',

  frigateHost: '',
  frigatePort: 5000,
  go2rtcHost: '',
  go2rtcPort: 1984,

  mqttHost: '',
  mqttPort: 1883,
  mqttUser: '',
  mqttPassword: '',
  mqttTopic: 'frigate/events',

  probeResult: null,
  isProbing: false,

  aiProvider: 'gemini',
  aiModel: 'gemini-2.5-flash',
  aiApiKey: '',
  aiHost: '',

  ttsEngine: 'piper',
  ttsVoice: 'en_US-lessac-medium',

  responseMode: 'live_operator',

  selectedCameras: {},

  isGenerating: false,
};

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

/**
 * Pure reducer for setup wizard state transitions.
 */
function setupReducer(state: SetupState, action: SetupAction): SetupState {
  switch (action.type) {
    case 'SET_STEP':
      return { ...state, currentStep: action.step };

    case 'SET_FRIGATE':
      return {
        ...state,
        frigateHost: action.host,
        frigatePort: action.port,
        // Mirror host to go2rtc and mqtt if they haven't been customised yet
        go2rtcHost: state.go2rtcHost || action.host,
        mqttHost: state.mqttHost || action.host,
      };

    case 'SET_GO2RTC':
      return { ...state, go2rtcHost: action.host, go2rtcPort: action.port };

    case 'SET_MQTT':
      return {
        ...state,
        mqttHost: action.host,
        mqttPort: action.port,
        mqttUser: action.user,
        mqttPassword: action.password,
        mqttTopic: action.topic,
      };

    case 'SET_PROBE_RESULT':
      return { ...state, probeResult: action.result, isProbing: false };

    case 'SET_PROBING':
      return { ...state, isProbing: action.value };

    case 'SET_AI':
      return {
        ...state,
        aiProvider: action.provider,
        aiModel: action.model,
        aiApiKey: action.apiKey,
        aiHost: action.host,
      };

    case 'SET_TTS':
      return { ...state, ttsEngine: action.engine, ttsVoice: action.voice };

    case 'SET_RESPONSE_MODE':
      return { ...state, responseMode: action.mode };

    case 'TOGGLE_CAMERA': {
      const cam = state.selectedCameras[action.name];
      return {
        ...state,
        selectedCameras: {
          ...state.selectedCameras,
          [action.name]: { ...cam!, enabled: action.enabled },
        },
      };
    }

    case 'SET_CAMERA_STREAM': {
      const cam = state.selectedCameras[action.name];
      return {
        ...state,
        selectedCameras: {
          ...state.selectedCameras,
          [action.name]: { ...cam!, go2rtc_stream: action.stream },
        },
      };
    }

    case 'INIT_CAMERAS':
      return { ...state, selectedCameras: action.cameras };

    case 'SET_GENERATING':
      return { ...state, isGenerating: action.value };

    case 'RESET':
      return { ...initialState };

    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Hook providing the setup wizard reducer state and typed dispatch.
 *
 * @returns state    — current SetupState
 * @returns dispatch — dispatch a SetupAction
 */
export function useSetupState(): {
  state: SetupState;
  dispatch: React.Dispatch<SetupAction>;
} {
  const [state, dispatch] = useReducer(setupReducer, initialState);
  return { state, dispatch };
}
