/**
 * SetupWizard — first-run guided configuration wizard controller.
 *
 * Manages the full 9-step flow from welcome to config generation:
 *   welcome → frigate → discovery → mqtt → ai → tts → mode → cameras → review
 *
 * Each step is a self-contained component. This controller wires them together
 * by passing state slices as props and handling navigation via the shared
 * useSetupState reducer.
 *
 * A progress bar at the top reflects the current step. All steps except
 * "welcome" have a Back button. Steps validate their inputs locally before
 * calling the onNext handler.
 *
 * The Frigate probe runs on the "frigate" step; results are stored in the
 * reducer and shared with the "discovery" and "cameras" steps so those
 * steps can display discovered cameras and backchannel info without re-fetching.
 */

import { useCallback, useEffect, useState } from 'react';
import { ChevronLeft } from 'lucide-react';
import { cn } from '@/utils/cn';
import { probeServices } from '@/api/setup';
import { useSetupState, SETUP_STEPS, type SetupStep } from './useSetupState';
import {
  WelcomeStep,
  FrigateStep,
  DiscoveryStep,
  MqttStep,
  AiProviderStep,
  TtsProviderStep,
  ResponseModeStep,
  CameraSelectStep,
  ReviewStep,
} from './steps';

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

/** Human-readable label for each step shown in the progress bar. */
const STEP_LABELS: Record<SetupStep, string> = {
  welcome: 'Welcome',
  frigate: 'Frigate',
  discovery: 'Discovery',
  mqtt: 'MQTT',
  ai: 'AI',
  tts: 'Voice',
  mode: 'Mode',
  cameras: 'Cameras',
  review: 'Review',
};

/** Steps that render a numbered dot in the progress indicator (welcome is dotless). */
const NUMBERED_STEPS = SETUP_STEPS.filter((s) => s !== 'welcome');

interface ProgressBarProps {
  currentStep: SetupStep;
}

/**
 * Horizontal step progress bar.
 * Welcome step hides the bar (it's the landing screen).
 */
function ProgressBar({ currentStep }: ProgressBarProps) {
  if (currentStep === 'welcome') return null;

  const active = NUMBERED_STEPS.indexOf(currentStep) + 1;

  return (
    <nav aria-label="Setup progress" className="mb-6 px-6 pt-6">
      {/* Desktop: numbered circles */}
      <ol className="hidden sm:flex items-center">
        {NUMBERED_STEPS.map((step, i) => {
          const num = i + 1;
          const isDone = num < active;
          const isCurrent = num === active;

          return (
            <li key={step} className="flex items-center flex-1 last:flex-none">
              <div className="flex flex-col items-center">
                <div
                  className={cn(
                    'flex h-7 w-7 items-center justify-center rounded-full border-2 text-xs font-semibold transition-colors',
                    isDone
                      ? 'border-blue-600 bg-blue-600 text-white'
                      : isCurrent
                        ? 'border-blue-500 bg-transparent text-blue-400'
                        : 'border-gray-600 bg-transparent text-gray-600',
                  )}
                  aria-current={isCurrent ? 'step' : undefined}
                >
                  {isDone ? (
                    <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 00-1.414 0L8 12.586 4.707 9.293a1 1 0 00-1.414 1.414l4 4a1 1 0 001.414 0l8-8a1 1 0 000-1.414z" clipRule="evenodd" />
                    </svg>
                  ) : (
                    num
                  )}
                </div>
                <span className={cn(
                  'mt-1 text-[10px] font-medium',
                  isCurrent ? 'text-blue-400' : isDone ? 'text-gray-500' : 'text-gray-600',
                )}>
                  {STEP_LABELS[step]}
                </span>
              </div>

              {i < NUMBERED_STEPS.length - 1 && (
                <div
                  className={cn(
                    'mx-1 h-px flex-1 transition-colors',
                    num < active ? 'bg-blue-600' : 'bg-gray-700',
                  )}
                  aria-hidden="true"
                />
              )}
            </li>
          );
        })}
      </ol>

      {/* Mobile: simple dot indicators */}
      <div className="flex sm:hidden items-center justify-center gap-1.5" aria-hidden="true">
        {NUMBERED_STEPS.map((step, i) => {
          const num = i + 1;
          return (
            <div
              key={step}
              className={cn(
                'h-1.5 rounded-full transition-all',
                num < active ? 'w-4 bg-blue-600' : num === active ? 'w-4 bg-blue-400' : 'w-1.5 bg-gray-600',
              )}
            />
          );
        })}
      </div>

      {/* Mobile: label */}
      <p className="mt-2 text-center text-xs text-blue-400 sm:hidden">
        Step {active} of {NUMBERED_STEPS.length} — {STEP_LABELS[currentStep]}
      </p>
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Back navigation
// ---------------------------------------------------------------------------

/** Returns the previous step for back navigation, or null on the first step. */
function prevStep(step: SetupStep): SetupStep | null {
  const i = SETUP_STEPS.indexOf(step);
  return i > 0 ? (SETUP_STEPS[i - 1] ?? null) : null;
}

// ---------------------------------------------------------------------------
// SetupWizard
// ---------------------------------------------------------------------------

/**
 * First-run setup wizard.
 *
 * Renders inside SetupPage (no AppShell). Steps live in src/components/setup/steps/.
 *
 * @example
 *   // Inside SetupPage:
 *   <SetupWizard />
 */
export function SetupWizard() {
  const { state, dispatch } = useSetupState();
  const [frigateError, setFrigateError] = useState<string | null>(null);

  const goTo = useCallback(
    (step: SetupStep) => dispatch({ type: 'SET_STEP', step }),
    [dispatch],
  );

  const back = prevStep(state.currentStep);

  const handleBack = () => {
    if (back) goTo(back);
  };

  /**
   * Runs the Frigate probe and advances to the discovery step.
   * Also seeds go2rtcHost and mqttHost from the Frigate host when they're empty.
   */
  const handleFrigateConnect = useCallback(
    async (host: string, port: number) => {
      setFrigateError(null);
      dispatch({ type: 'SET_FRIGATE', host, port });
      dispatch({ type: 'SET_PROBING', value: true });

      try {
        const result = await probeServices({
          frigate_host: host,
          frigate_port: port,
          go2rtc_host: state.go2rtcHost || host,
          go2rtc_port: state.go2rtcPort,
          mqtt_host: state.mqttHost || host,
          mqtt_port: state.mqttPort,
        });
        dispatch({ type: 'SET_PROBE_RESULT', result });

        // Pre-fill MQTT host from Frigate host if not yet set
        if (!state.mqttHost) {
          dispatch({
            type: 'SET_MQTT',
            host: result.mqtt_reachable ? (state.mqttHost || host) : host,
            port: state.mqttPort,
            user: state.mqttUser,
            password: state.mqttPassword,
            topic: state.mqttTopic,
          });
        }

        goTo('discovery');
      } catch (err) {
        dispatch({ type: 'SET_PROBING', value: false });
        const msg = err instanceof Error ? err.message : 'Could not reach Frigate. Check the hostname and try again.';
        setFrigateError(msg);
      }
    },
    [dispatch, goTo, state.go2rtcHost, state.go2rtcPort, state.mqttHost, state.mqttPort, state.mqttUser, state.mqttPassword, state.mqttTopic],
  );

  /**
   * When the probe result arrives, initialize the selectedCameras map.
   * Pre-check cameras that have a detected backchannel.
   */
  useEffect(() => {
    if (!state.probeResult) return;
    // Only initialise if not already populated (avoid overwriting user selections on re-render)
    if (Object.keys(state.selectedCameras).length > 0) return;

    const cameras: Record<string, { enabled: boolean; go2rtc_stream: string; audio_codec?: string }> = {};

    for (const camName of state.probeResult.frigate_cameras) {
      const info = state.probeResult.backchannel_info[camName];
      const hasBackchannel = info?.has_backchannel ?? false;
      // Best matching go2rtc stream name — prefer exact match
      const stream = state.probeResult.go2rtc_streams.includes(camName)
        ? camName
        : (state.probeResult.go2rtc_streams[0] ?? camName);
      const codec = info?.codecs[0];

      cameras[camName] = {
        enabled: hasBackchannel,
        go2rtc_stream: stream,
        ...(codec ? { audio_codec: codec } : {}),
      };
    }

    dispatch({ type: 'INIT_CAMERAS', cameras });
  }, [state.probeResult, state.selectedCameras, dispatch]);

  // probeError is set in the catch block of handleFrigateConnect
  // Cleared when the user types a new host or retries

  return (
    <div className="space-y-0">
      {/* Progress indicator (hidden on welcome) */}
      <ProgressBar currentStep={state.currentStep} />

      {/* Back button */}
      {back && state.currentStep !== 'welcome' && (
        <div className="px-6 pb-2">
          <button
            onClick={handleBack}
            className={cn(
              'flex items-center gap-1.5 text-sm font-medium transition-colors',
              'text-gray-500 hover:text-gray-200',
              'focus:outline-none focus:ring-2 focus:ring-blue-500 rounded',
            )}
          >
            <ChevronLeft className="h-4 w-4" />
            Back
          </button>
        </div>
      )}

      {/* Active step */}
      <div>
        {state.currentStep === 'welcome' && (
          <WelcomeStep onNext={() => goTo('frigate')} />
        )}

        {state.currentStep === 'frigate' && (
          <FrigateStep
            initialHost={state.frigateHost}
            initialPort={state.frigatePort}
            isProbing={state.isProbing}
            probeError={frigateError}
            onConnect={handleFrigateConnect}
          />
        )}

        {state.currentStep === 'discovery' && state.probeResult && (
          <DiscoveryStep
            probeResult={state.probeResult}
            go2rtcHost={state.go2rtcHost || state.frigateHost}
            go2rtcPort={state.go2rtcPort}
            mqttHost={state.mqttHost || state.frigateHost}
            mqttPort={state.mqttPort}
            onGo2rtcChange={(host, port) =>
              dispatch({ type: 'SET_GO2RTC', host, port })
            }
            onMqttHostChange={(host, port) =>
              dispatch({
                type: 'SET_MQTT',
                host,
                port,
                user: state.mqttUser,
                password: state.mqttPassword,
                topic: state.mqttTopic,
              })
            }
            onNext={() => goTo('mqtt')}
          />
        )}

        {state.currentStep === 'mqtt' && (
          <MqttStep
            mqttHost={state.mqttHost || state.frigateHost}
            mqttPort={state.mqttPort}
            mqttUser={state.mqttUser}
            mqttPassword={state.mqttPassword}
            mqttTopic={state.mqttTopic}
            alreadyConnected={state.probeResult?.mqtt_reachable ?? false}
            frigateHost={state.frigateHost}
            onNext={(host, port, user, password, topic) => {
              dispatch({ type: 'SET_MQTT', host, port, user, password, topic });
              goTo('ai');
            }}
          />
        )}

        {state.currentStep === 'ai' && (
          <AiProviderStep
            provider={state.aiProvider}
            model={state.aiModel}
            apiKey={state.aiApiKey}
            aiHost={state.aiHost}
            onNext={(provider, model, apiKey, host) => {
              dispatch({ type: 'SET_AI', provider, model, apiKey, host });
              goTo('tts');
            }}
          />
        )}

        {state.currentStep === 'tts' && (
          <TtsProviderStep
            ttsEngine={state.ttsEngine}
            ttsVoice={state.ttsVoice}
            responseMode={state.responseMode}
            onNext={(engine, voice) => {
              dispatch({ type: 'SET_TTS', engine, voice });
              goTo('mode');
            }}
          />
        )}

        {state.currentStep === 'mode' && (
          <ResponseModeStep
            responseMode={state.responseMode}
            ttsEngine={state.ttsEngine}
            ttsVoice={state.ttsVoice}
            onNext={(mode) => {
              dispatch({ type: 'SET_RESPONSE_MODE', mode });
              goTo('cameras');
            }}
          />
        )}

        {state.currentStep === 'cameras' && state.probeResult && (
          <CameraSelectStep
            probeResult={state.probeResult}
            selectedCameras={state.selectedCameras}
            onCameraToggle={(name, enabled) =>
              dispatch({ type: 'TOGGLE_CAMERA', name, enabled })
            }
            onStreamChange={(name, stream) =>
              dispatch({ type: 'SET_CAMERA_STREAM', name, stream })
            }
            onNext={() => goTo('review')}
          />
        )}

        {state.currentStep === 'cameras' && !state.probeResult && (
          // Fallback if the user somehow reaches cameras without a probe result
          <div className="px-6 py-8 text-center text-sm text-gray-500">
            No probe result available. Please go back and run the Frigate connection step.
          </div>
        )}

        {state.currentStep === 'review' && (
          <ReviewStep state={state} />
        )}
      </div>
    </div>
  );
}
