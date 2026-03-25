/**
 * Wizard step components — all 7 steps in one file.
 *
 * Each step is a focused, single-responsibility component exported by name.
 * CameraSetupWizard.tsx conditionally renders whichever step is active.
 *
 * Steps in order:
 *   WizardStepCamera    — pick a camera from the grid
 *   WizardStepAnalysis  — probe go2rtc for backchannel / codecs
 *   WizardStepTest      — push a live test tone, report result
 *   WizardStepSuccess   — confirm what worked, continue to configure
 *   WizardStepRetry     — auto-retry with different codecs / settings
 *   WizardStepConfigure — fill in scene context, save to config
 *   WizardStepVerify    — final live push with saved settings, then Finish
 */

import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import {
  Camera,
  Mic,
  Volume2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Loader,
  Settings,
  ChevronRight,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { inputCls, Field } from '@/components/common/FormField';
import { useServiceStatus } from '@/hooks/useServiceStatus';
import {
  detectCamera,
  testWizardAudio,
  saveWizardCamera,
} from '@/api/wizard';
import type { DetectResponse, WizardTestResponse, WizardSaveRequest } from '@/api/wizard';

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

/**
 * Full-width error banner with an XCircle icon and a "Try Again" button.
 *
 * @param message - Error text to display
 * @param onRetry  - Called when the user clicks "Try Again"
 */
function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl bg-red-50 p-4 text-sm text-red-800 dark:bg-red-950/20 dark:text-red-300">
      <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0" />
      <div className="flex-1">
        <p className="font-semibold">Something went wrong</p>
        <p className="mt-0.5 opacity-80">{message}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-2 text-xs font-semibold underline underline-offset-2 hover:opacity-70"
          >
            Try Again
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Centered spinner with an optional label line below.
 */
function SpinnerBlock({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-gray-500 dark:text-gray-400">
      <Loader className="h-8 w-8 animate-spin text-blue-500" />
      <p className="text-sm font-medium">{label}</p>
    </div>
  );
}

/**
 * Codec pill badge — renders the raw go2rtc codec string in a readable chip.
 */
function CodecPill({ codec }: { codec: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-mono font-semibold text-blue-700 dark:border-blue-700/40 dark:bg-blue-950/30 dark:text-blue-300">
      {codec}
    </span>
  );
}

/** Maps internal codec keys to human-readable labels for the summary table. */
function codecLabel(codec: string): string {
  const map: Record<string, string> = {
    pcm_mulaw: 'G.711 mu-law (PCMU)',
    pcm_alaw: 'G.711 A-law (PCMA)',
    aac: 'AAC',
    opus: 'Opus',
  };
  return map[codec] ?? codec;
}

// ---------------------------------------------------------------------------
// Step 1: WizardStepCamera
// ---------------------------------------------------------------------------

export interface WizardStepCameraProps {
  /** Called with the camera name the user selected. */
  onSelect: (cameraName: string) => void;
}

/**
 * Step 1 — Camera selection grid.
 *
 * Loads the camera list from useServiceStatus and renders each camera as a
 * clickable card with a snapshot thumbnail and a backchannel badge.
 * Cameras not yet in VoxWatch config are included so operators can enroll
 * new cameras through the wizard.
 */
export function WizardStepCamera({ onSelect }: WizardStepCameraProps) {
  const { status, isLoading } = useServiceStatus();
  const allCameras = status?.cameras ?? [];

  return (
    <div className="p-5 space-y-4">
      <div>
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Select a Camera
        </h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Choose the camera you want to configure for audio deterrent.
          Gray cameras are visible in go2rtc but not yet in VoxWatch.
        </p>
      </div>

      {isLoading && <SpinnerBlock label="Loading cameras..." />}

      {!isLoading && allCameras.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-10 text-gray-400">
          <Camera className="h-10 w-10" />
          <p className="text-sm">No cameras found. Check Frigate and go2rtc connections.</p>
        </div>
      )}

      {!isLoading && allCameras.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {allCameras.map((cam) => (
            <button
              key={cam.name}
              onClick={() => onSelect(cam.name)}
              className={cn(
                'group relative flex flex-col overflow-hidden rounded-xl border-2 text-left transition-all',
                'focus:outline-none focus:ring-2 focus:ring-blue-500',
                'active:scale-[0.98]',
                cam.enabled
                  ? 'border-gray-200 hover:border-blue-400 dark:border-gray-700 dark:hover:border-blue-500'
                  : 'border-gray-200/50 hover:border-gray-400 dark:border-gray-700/50 dark:hover:border-gray-500',
              )}
            >
              {/* Snapshot thumbnail */}
              <div className="relative h-28 w-full overflow-hidden bg-gray-100 dark:bg-gray-800">
                <img
                  src={`/api/cameras/${cam.name}/snapshot`}
                  alt={`${cam.name} snapshot`}
                  className="h-full w-full object-cover transition-transform group-hover:scale-105"
                  loading="lazy"
                  onError={(e) => {
                    // Replace broken snapshot with a placeholder icon
                    (e.currentTarget as HTMLImageElement).style.display = 'none';
                  }}
                />
                {/* Backchannel badge — top-right overlay */}
                <div className="absolute right-2 top-2">
                  {cam.has_backchannel === true ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-green-600 px-2 py-0.5 text-xs font-semibold text-white shadow">
                      <Mic className="h-3 w-3" />
                      Audio
                    </span>
                  ) : cam.has_backchannel === false ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-yellow-500 px-2 py-0.5 text-xs font-semibold text-white shadow">
                      <AlertTriangle className="h-3 w-3" />
                      No audio?
                    </span>
                  ) : null}
                </div>
              </div>

              {/* Card footer */}
              <div className="flex items-center justify-between px-3 py-2.5">
                <div>
                  <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {cam.name}
                  </p>
                  {!cam.enabled && (
                    <p className="text-xs text-gray-400 dark:text-gray-500">
                      not configured
                    </p>
                  )}
                </div>
                <ChevronRight className="h-4 w-4 text-gray-400 group-hover:text-blue-500 transition-colors" />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2: WizardStepAnalysis
// ---------------------------------------------------------------------------

export interface WizardStepAnalysisProps {
  cameraName: string;
  /** Called with the detect result when the probe succeeds. */
  onComplete: (result: DetectResponse) => void;
  /** Called if the user wants to go back and pick a different camera. */
  onError: () => void;
}

/**
 * Step 2 — Stream analysis.
 *
 * Fires the /wizard/detect probe automatically on mount. Shows a spinner
 * while loading, then displays backchannel status and detected codec pills.
 * If backchannel is absent the operator can check "My camera has a speaker"
 * to proceed anyway (the test step will reveal whether audio actually works).
 */
export function WizardStepAnalysis({
  cameraName,
  onComplete,
  onError: _onError,
}: WizardStepAnalysisProps) {
  const [backchannelOverride, setBackchannelOverride] = useState(false);

  const detectMutation = useMutation({
    mutationFn: detectCamera,
  });

  // Fire the probe on mount
  useEffect(() => {
    detectMutation.mutate({ camera_name: cameraName });
    // Intentionally run once on mount only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const result = detectMutation.data;
  const hasBackchannel = result?.has_backchannel || backchannelOverride;

  return (
    <div className="p-5 space-y-5">
      <div>
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Analyzing Stream
        </h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Probing go2rtc for backchannel support on{' '}
          <span className="font-mono text-gray-700 dark:text-gray-300">{cameraName}</span>.
        </p>
      </div>

      {detectMutation.isPending && <SpinnerBlock label="Analyzing stream..." />}

      {detectMutation.isError && (
        <ErrorBanner
          message={
            (detectMutation.error as { userMessage?: string })?.userMessage ??
            'Failed to probe camera stream.'
          }
          onRetry={() => detectMutation.mutate({ camera_name: cameraName })}
        />
      )}

      {result && (
        <div className="space-y-4">
          {/* Stream name */}
          <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3 dark:bg-gray-800/50">
            <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
              go2rtc stream
            </span>
            <span className="font-mono text-sm font-semibold text-gray-800 dark:text-gray-200">
              {result.stream_name}
            </span>
          </div>

          {/* Backchannel status */}
          {result.has_backchannel ? (
            <div className="flex items-start gap-3 rounded-xl bg-green-50 p-4 dark:bg-green-950/20">
              <CheckCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-green-600 dark:text-green-400" />
              <div>
                <p className="text-sm font-semibold text-green-700 dark:text-green-400">
                  Two-way audio detected
                </p>
                <p className="mt-0.5 text-xs text-green-600 dark:text-green-500">
                  go2rtc found an RTSP backchannel track on this stream.
                </p>
              </div>
            </div>
          ) : (
            <div className="rounded-xl bg-yellow-50 p-4 dark:bg-yellow-950/20 space-y-3">
              <div className="flex items-start gap-3">
                <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-yellow-600 dark:text-yellow-400" />
                <div>
                  <p className="text-sm font-semibold text-yellow-700 dark:text-yellow-400">
                    No backchannel detected
                  </p>
                  <p className="mt-0.5 text-xs text-yellow-600 dark:text-yellow-500">
                    go2rtc did not find a backchannel track on the current stream.
                    Some cameras expose it on a different stream profile.
                  </p>
                </div>
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-yellow-800 dark:text-yellow-300">
                <input
                  type="checkbox"
                  checked={backchannelOverride}
                  onChange={(e) => setBackchannelOverride(e.target.checked)}
                  className="h-4 w-4 rounded border-yellow-400 accent-yellow-600"
                />
                My camera has a speaker — try anyway
              </label>
            </div>
          )}

          {/* Detected codecs */}
          {result.codecs.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium text-gray-500 dark:text-gray-400">
                Detected codecs
              </p>
              <div className="flex flex-wrap gap-2">
                {result.codecs.map((c) => (
                  <CodecPill key={c} codec={c} />
                ))}
              </div>
            </div>
          )}

          {/* Continue button — only enabled when backchannel is known (or overridden) */}
          <button
            onClick={() => onComplete({ ...result, has_backchannel: hasBackchannel })}
            disabled={!hasBackchannel && !result.has_backchannel}
            className={cn(
              'flex w-full items-center justify-center gap-2 rounded-xl px-4 py-4 text-base font-semibold text-white transition-all',
              'focus:outline-none focus:ring-2 focus:ring-blue-500',
              'active:scale-[0.98]',
              hasBackchannel || result.has_backchannel
                ? 'bg-blue-600 hover:bg-blue-700'
                : 'cursor-not-allowed bg-gray-300 dark:bg-gray-700',
            )}
          >
            Continue to Audio Test
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3: WizardStepTest
// ---------------------------------------------------------------------------

/** Possible states of the test push within this step. */
type TestPhase = 'idle' | 'connecting' | 'sending' | 'listening' | 'done';

export interface WizardStepTestProps {
  cameraName: string;
  streamName: string;
  codec: string;
  warmupDelay: number;
  /** Called when the operator confirms they heard audio clearly. */
  onHeard: (result: WizardTestResponse) => void;
  /** Called when the operator heard nothing. */
  onNoAudio: (result: WizardTestResponse) => void;
  /** Called when audio was partial or distorted. */
  onPartial: (result: WizardTestResponse) => void;
}

/**
 * Step 3 — Live audio test push.
 *
 * Walks through visual phases (connecting → sending → listening) timed to
 * the warmup delay so the operator knows what to expect at the camera.
 * After the push completes the operator self-reports what they heard via
 * three large tap-target buttons.
 */
export function WizardStepTest({
  cameraName,
  streamName,
  codec,
  warmupDelay,
  onHeard,
  onNoAudio,
  onPartial,
}: WizardStepTestProps) {
  const [phase, setPhase] = useState<TestPhase>('idle');

  const testMutation = useMutation({
    mutationFn: testWizardAudio,
    onSuccess: () => setPhase('done'),
    onError: () => setPhase('idle'),
  });

  /** Drive the visual phases while the mutation is in-flight. */
  const handleTest = () => {
    setPhase('connecting');
    const sendDelay = Math.min(warmupDelay * 1000, 3000);

    // After warmup show "sending", then switch to "listening" once done
    const t1 = setTimeout(() => setPhase('sending'), sendDelay);

    testMutation.mutate(
      { camera_name: cameraName, stream_name: streamName, codec, warmup_delay: warmupDelay },
      {
        onSettled: () => {
          clearTimeout(t1);
          setPhase('done');
        },
      },
    );
  };

  const phaseLabel: Record<TestPhase, string> = {
    idle: 'Test Audio',
    connecting: 'Establishing backchannel...',
    sending: 'Sending test tone...',
    listening: 'Listen for audio',
    done: 'Test complete',
  };

  const testResult = testMutation.data;

  return (
    <div className="p-5 space-y-5">
      <div>
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Audio Test
        </h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Press the button and listen at{' '}
          <span className="font-mono text-gray-700 dark:text-gray-300">{cameraName}</span>{' '}
          for a test tone.
        </p>
      </div>

      {/* Warning note */}
      <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2.5 text-xs text-amber-700 dark:bg-amber-950/20 dark:text-amber-400">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
        <span>
          The camera video stream may briefly disconnect while the backchannel is open.
          This is normal and resolves automatically.
        </span>
      </div>

      {/* Big test button */}
      <button
        onClick={handleTest}
        disabled={testMutation.isPending || phase === 'done'}
        className={cn(
          'flex w-full items-center justify-center gap-3 rounded-xl px-4 py-4 text-base font-semibold text-white transition-all',
          'focus:outline-none focus:ring-2 focus:ring-blue-500',
          'active:scale-[0.98]',
          'disabled:cursor-not-allowed disabled:opacity-60',
          testMutation.isPending
            ? 'bg-blue-500'
            : phase === 'done'
              ? 'bg-gray-400'
              : 'bg-blue-600 hover:bg-blue-700',
        )}
      >
        {testMutation.isPending ? (
          <Loader className="h-5 w-5 animate-spin" />
        ) : (
          <Volume2 className="h-5 w-5" />
        )}
        {phaseLabel[phase]}
      </button>

      {/* API error */}
      {testMutation.isError && (
        <ErrorBanner
          message={
            (testMutation.error as { userMessage?: string })?.userMessage ??
            'Backend error during audio push.'
          }
          onRetry={handleTest}
        />
      )}

      {/* Response buttons — shown after test completes */}
      {phase === 'done' && testResult && (
        <div className="space-y-2">
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
            What did you hear at the camera?
          </p>

          <button
            onClick={() => onHeard(testResult)}
            className={cn(
              'flex w-full items-center gap-3 rounded-xl border-2 border-green-500 bg-green-50 px-4 py-3.5 text-sm font-semibold text-green-700',
              'hover:bg-green-100 active:scale-[0.98] transition-all',
              'focus:outline-none focus:ring-2 focus:ring-green-500',
              'dark:border-green-700 dark:bg-green-950/20 dark:text-green-300 dark:hover:bg-green-950/40',
            )}
          >
            <CheckCircle className="h-5 w-5 flex-shrink-0" />
            Yes, I heard it clearly
          </button>

          <button
            onClick={() => onPartial(testResult)}
            className={cn(
              'flex w-full items-center gap-3 rounded-xl border-2 border-yellow-400 bg-yellow-50 px-4 py-3.5 text-sm font-semibold text-yellow-700',
              'hover:bg-yellow-100 active:scale-[0.98] transition-all',
              'focus:outline-none focus:ring-2 focus:ring-yellow-400',
              'dark:border-yellow-600 dark:bg-yellow-950/20 dark:text-yellow-300 dark:hover:bg-yellow-950/40',
            )}
          >
            <AlertTriangle className="h-5 w-5 flex-shrink-0" />
            Partial or distorted audio
          </button>

          <button
            onClick={() => onNoAudio(testResult)}
            className={cn(
              'flex w-full items-center gap-3 rounded-xl border-2 border-red-400 bg-red-50 px-4 py-3.5 text-sm font-semibold text-red-700',
              'hover:bg-red-100 active:scale-[0.98] transition-all',
              'focus:outline-none focus:ring-2 focus:ring-red-400',
              'dark:border-red-700 dark:bg-red-950/20 dark:text-red-300 dark:hover:bg-red-950/40',
            )}
          >
            <XCircle className="h-5 w-5 flex-shrink-0" />
            No audio heard
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4: WizardStepSuccess
// ---------------------------------------------------------------------------

export interface WizardStepSuccessProps {
  cameraName: string;
  streamName: string;
  codec: string;
  warmupDelay: number;
  testResult: WizardTestResponse;
  /** Advance to the Configure step. */
  onContinue: () => void;
}

/**
 * Step 4 — Audio confirmed working.
 *
 * Displays a green success banner and a summary table of the working
 * configuration so the operator can see exactly what succeeded before
 * advancing to the configure step.
 */
export function WizardStepSuccess({
  cameraName,
  streamName,
  codec,
  warmupDelay,
  testResult,
  onContinue,
}: WizardStepSuccessProps) {
  return (
    <div className="p-5 space-y-5">
      {/* Green success banner */}
      <div className="flex items-start gap-3 rounded-xl bg-green-50 p-4 dark:bg-green-950/20">
        <CheckCircle className="mt-0.5 h-6 w-6 flex-shrink-0 text-green-600 dark:text-green-400" />
        <div>
          <p className="text-base font-semibold text-green-800 dark:text-green-300">
            Audio is working!
          </p>
          <p className="mt-0.5 text-sm text-green-600 dark:text-green-500">
            {testResult.message}
          </p>
        </div>
      </div>

      {/* Summary table */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-700/50 overflow-hidden">
        <table className="w-full text-sm">
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {(
              [
                ['Camera', cameraName],
                ['Stream', streamName],
                ['Working codec', codecLabel(codec)],
                ['Warmup delay', `${warmupDelay}s`],
                ['Response time', `${testResult.response_time_ms} ms`],
              ] as [string, string][]
            ).map(([label, value]) => (
              <tr key={label}>
                <td className="px-4 py-3 text-gray-500 dark:text-gray-400 w-36">
                  {label}
                </td>
                <td className="px-4 py-3 font-semibold font-mono text-gray-900 dark:text-gray-100 break-all">
                  {value}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button
        onClick={onContinue}
        className={cn(
          'flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-4 text-base font-semibold text-white',
          'hover:bg-blue-700 active:scale-[0.98] transition-all',
          'focus:outline-none focus:ring-2 focus:ring-blue-500',
        )}
      >
        Continue to Setup
        <ChevronRight className="h-5 w-5" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 5: WizardStepRetry
// ---------------------------------------------------------------------------

/** Codecs available in the manual override dropdown. */
const CODEC_OPTIONS = [
  { value: 'pcm_mulaw', label: 'G.711 mu-law (PCMU)' },
  { value: 'pcm_alaw', label: 'G.711 A-law (PCMA)' },
  { value: 'aac', label: 'AAC' },
  { value: 'opus', label: 'Opus' },
] as const;

/** Maximum auto-retry attempts before showing the manual override panel. */
const MAX_AUTO_RETRIES = 3;

export interface WizardStepRetryProps {
  cameraName: string;
  streamName: string;
  detectResult: DetectResponse | null;
  retryAttempt: number;
  warmupDelay: number;
  /** Operator confirmed the retry attempt worked. */
  onHeard: (codec: string, result: WizardTestResponse) => void;
  /** Retry attempt also failed. */
  onNoAudio: (codec: string, result: WizardTestResponse) => void;
  /** Skip audio testing and go straight to manual configure. */
  onSkip: () => void;
}

/**
 * Step 5 — Retry with different settings.
 *
 * For the first MAX_AUTO_RETRIES attempts the wizard automatically picks the
 * next codec and shows a spinner. After that a manual override panel appears
 * with a codec dropdown and warmup slider.
 */
export function WizardStepRetry({
  cameraName,
  streamName,
  detectResult,
  retryAttempt,
  warmupDelay: initialWarmup,
  onHeard,
  onNoAudio,
  onSkip,
}: WizardStepRetryProps) {
  // Manual override controls — only shown after MAX_AUTO_RETRIES
  const [manualCodec, setManualCodec] = useState<string>('pcm_mulaw');
  const [manualWarmup, setManualWarmup] = useState<number>(initialWarmup);
  const [retryPhase, setRetryPhase] = useState<'idle' | 'running' | 'done'>('idle');

  const isManual = retryAttempt >= MAX_AUTO_RETRIES;

  // Pick the next codec to auto-try based on what the detect probe found
  const autoCodecs = detectResult?.codecs ?? [];
  const tryCodec = isManual
    ? manualCodec
    : autoCodecs[retryAttempt % Math.max(autoCodecs.length, 1)] ?? 'pcm_alaw';

  const retryMutation = useMutation({
    mutationFn: testWizardAudio,
    onSuccess: () => setRetryPhase('done'),
    onError: () => setRetryPhase('idle'),
  });

  // Auto-fire on mount for non-manual retries
  useEffect(() => {
    if (!isManual) {
      setRetryPhase('running');
      retryMutation.mutate({
        camera_name: cameraName,
        stream_name: streamName,
        codec: tryCodec,
        warmup_delay: initialWarmup,
      });
    }
    // Only run on mount; intentional dep omission
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleManualTest = () => {
    setRetryPhase('running');
    retryMutation.mutate({
      camera_name: cameraName,
      stream_name: streamName,
      codec: manualCodec,
      warmup_delay: manualWarmup,
    });
  };

  const retryResult = retryMutation.data;

  return (
    <div className="p-5 space-y-5">
      <div>
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Let's try different settings
        </h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Attempt {retryAttempt} — trying another codec or configuration.
        </p>
      </div>

      {/* Auto-retry spinner */}
      {!isManual && retryPhase === 'running' && (
        <div className="flex items-center gap-3 rounded-xl bg-blue-50 p-4 dark:bg-blue-950/20">
          <Loader className="h-5 w-5 animate-spin text-blue-500" />
          <p className="text-sm font-medium text-blue-700 dark:text-blue-300">
            Trying <span className="font-mono">{tryCodec}</span>…
          </p>
        </div>
      )}

      {/* API error */}
      {retryMutation.isError && (
        <ErrorBanner
          message={
            (retryMutation.error as { userMessage?: string })?.userMessage ??
            'Backend error during retry.'
          }
          {...(isManual ? { onRetry: handleManualTest } : {})}
        />
      )}

      {/* Manual override panel */}
      {isManual && (
        <div className="space-y-4 rounded-xl border border-gray-200 p-4 dark:border-gray-700/50">
          <p className="text-sm font-semibold text-gray-800 dark:text-gray-200">
            Manual Override
          </p>

          <Field label="Audio codec">
            <select
              value={manualCodec}
              onChange={(e) => setManualCodec(e.target.value)}
              className={inputCls(false)}
            >
              {CODEC_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label={`Warmup delay: ${manualWarmup}s`}
            hint="Increase if the camera is slow to open the backchannel."
          >
            <input
              type="range"
              min={1}
              max={5}
              step={1}
              value={manualWarmup}
              onChange={(e) => setManualWarmup(Number(e.target.value))}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-xs text-gray-400 dark:text-gray-500 px-0.5">
              {[1, 2, 3, 4, 5].map((v) => (
                <span key={v}>{v}s</span>
              ))}
            </div>
          </Field>

          <button
            onClick={handleManualTest}
            disabled={retryMutation.isPending}
            className={cn(
              'flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3.5 text-sm font-semibold text-white',
              'hover:bg-blue-700 active:scale-[0.98] transition-all',
              'focus:outline-none focus:ring-2 focus:ring-blue-500',
              'disabled:cursor-not-allowed disabled:opacity-50',
            )}
          >
            {retryMutation.isPending ? (
              <Loader className="h-4 w-4 animate-spin" />
            ) : (
              <Volume2 className="h-4 w-4" />
            )}
            Test with these settings
          </button>
        </div>
      )}

      {/* Response buttons after retry push */}
      {retryPhase === 'done' && retryResult && (
        <div className="space-y-2">
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
            What did you hear?
          </p>

          <button
            onClick={() => onHeard(isManual ? manualCodec : tryCodec, retryResult)}
            className={cn(
              'flex w-full items-center gap-3 rounded-xl border-2 border-green-500 bg-green-50 px-4 py-3.5 text-sm font-semibold text-green-700',
              'hover:bg-green-100 active:scale-[0.98] transition-all',
              'focus:outline-none focus:ring-2 focus:ring-green-500',
              'dark:border-green-700 dark:bg-green-950/20 dark:text-green-300 dark:hover:bg-green-950/40',
            )}
          >
            <CheckCircle className="h-5 w-5 flex-shrink-0" />
            Yes, I heard it
          </button>

          <button
            onClick={() => onNoAudio(isManual ? manualCodec : tryCodec, retryResult)}
            className={cn(
              'flex w-full items-center gap-3 rounded-xl border-2 border-red-400 bg-red-50 px-4 py-3.5 text-sm font-semibold text-red-700',
              'hover:bg-red-100 active:scale-[0.98] transition-all',
              'focus:outline-none focus:ring-2 focus:ring-red-400',
              'dark:border-red-700 dark:bg-red-950/20 dark:text-red-300 dark:hover:bg-red-950/40',
            )}
          >
            <XCircle className="h-5 w-5 flex-shrink-0" />
            Still no audio
          </button>
        </div>
      )}

      {/* Skip link — always available */}
      <div className="pt-1 text-center">
        <button
          onClick={onSkip}
          className="text-sm text-gray-400 underline underline-offset-2 hover:text-gray-600 dark:hover:text-gray-300"
        >
          Skip, configure manually
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 6: WizardStepConfigure
// ---------------------------------------------------------------------------

export interface WizardStepConfigureProps {
  cameraName: string;
  streamName: string;
  selectedCodec: string | null;
  sceneContext: string;
  onSceneContextChange: (value: string) => void;
  /** Called after a successful /wizard/save response. */
  onSaved: () => void;
}

/**
 * Step 6 — Final configuration form.
 *
 * Lets the operator review the resolved settings (stream, codec), toggle
 * whether to enable the camera immediately, and optionally add a scene
 * description that the AI uses for context when generating audio warnings.
 */
export function WizardStepConfigure({
  cameraName,
  streamName,
  selectedCodec,
  sceneContext,
  onSceneContextChange,
  onSaved,
}: WizardStepConfigureProps) {
  const [enabled, setEnabled] = useState(true);
  const [audioCodec, setAudioCodec] = useState(selectedCodec ?? 'pcm_mulaw');

  const saveMutation = useMutation({
    mutationFn: saveWizardCamera,
    onSuccess: (data) => {
      if (data.success) onSaved();
    },
  });

  const handleSave = () => {
    const trimmedContext = sceneContext.trim();
    const req: WizardSaveRequest = {
      camera_name: cameraName,
      go2rtc_stream: streamName,
      audio_codec: audioCodec,
      enabled,
      ...(trimmedContext ? { scene_context: trimmedContext } : {}),
    };
    saveMutation.mutate(req);
  };

  return (
    <div className="p-5 space-y-5">
      <div>
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Configure Camera
        </h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Review the settings and optionally add context to help the AI generate
          better audio warnings.
        </p>
      </div>

      <div className="space-y-4">
        {/* Enabled toggle */}
        <div className="flex items-center justify-between rounded-xl border border-gray-200 px-4 py-3 dark:border-gray-700/50">
          <div>
            <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Enable immediately
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              VoxWatch will start monitoring this camera on save.
            </p>
          </div>
          <button
            role="switch"
            aria-checked={enabled}
            onClick={() => setEnabled((v) => !v)}
            className={cn(
              'relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
              'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
              enabled ? 'bg-blue-600' : 'bg-gray-300 dark:bg-gray-600',
            )}
          >
            <span
              className={cn(
                'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform',
                enabled ? 'translate-x-5' : 'translate-x-0',
              )}
            />
          </button>
        </div>

        {/* go2rtc stream — read-only */}
        <Field label="go2rtc stream" hint="Resolved automatically from go2rtc.">
          <input
            type="text"
            value={streamName}
            readOnly
            className={cn(inputCls(false), 'cursor-not-allowed opacity-70')}
          />
        </Field>

        {/* Audio codec */}
        <Field label="Audio codec">
          <select
            value={audioCodec}
            onChange={(e) => setAudioCodec(e.target.value)}
            className={inputCls(false)}
          >
            {CODEC_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>

        {/* Scene context */}
        <Field
          label="Scene context (optional)"
          hint="Describe the camera location and situation. The AI includes this when generating audio warnings."
        >
          <textarea
            rows={3}
            value={sceneContext}
            onChange={(e) => onSceneContextChange(e.target.value)}
            placeholder="e.g. front driveway, residential property, daytime monitoring"
            className={cn(
              inputCls(false),
              'resize-none',
              'py-2',
            )}
          />
        </Field>
      </div>

      {/* API error */}
      {saveMutation.isError && (
        <ErrorBanner
          message={
            (saveMutation.error as { userMessage?: string })?.userMessage ??
            'Failed to save configuration.'
          }
          onRetry={handleSave}
        />
      )}

      {saveMutation.isSuccess && !saveMutation.data?.success && (
        <ErrorBanner
          message={saveMutation.data?.message ?? 'Save did not complete successfully.'}
          onRetry={handleSave}
        />
      )}

      <button
        onClick={handleSave}
        disabled={saveMutation.isPending}
        className={cn(
          'flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-4 text-base font-semibold text-white',
          'hover:bg-blue-700 active:scale-[0.98] transition-all',
          'focus:outline-none focus:ring-2 focus:ring-blue-500',
          'disabled:cursor-not-allowed disabled:opacity-50',
        )}
      >
        {saveMutation.isPending ? (
          <Loader className="h-5 w-5 animate-spin" />
        ) : (
          <Settings className="h-5 w-5" />
        )}
        {saveMutation.isPending ? 'Saving...' : 'Save and Enable'}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 7: WizardStepVerify
// ---------------------------------------------------------------------------

export interface WizardStepVerifyProps {
  cameraName: string;
  streamName: string;
  codec: string | null;
  warmupDelay: number;
  /** Navigate away from the wizard (e.g. to /cameras). */
  onFinish: () => void;
  /** Reset the wizard to enroll another camera. */
  onSetupAnother: () => void;
}

/**
 * Step 7 — Final verification push.
 *
 * Fires a live test push automatically on mount using the saved codec.
 * A green banner indicates success; an amber banner with tips indicates
 * failure. Both paths offer "Finish" and "Set Up Another Camera" buttons.
 */
export function WizardStepVerify({
  cameraName,
  streamName,
  codec,
  warmupDelay,
  onFinish,
  onSetupAnother,
}: WizardStepVerifyProps) {
  const verifyMutation = useMutation({
    mutationFn: testWizardAudio,
  });

  // Auto-fire verification push on mount
  useEffect(() => {
    verifyMutation.mutate({
      camera_name: cameraName,
      stream_name: streamName,
      codec: codec ?? 'pcm_mulaw',
      warmup_delay: warmupDelay,
    });
    // Intentionally run once on mount only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const result = verifyMutation.data;
  const isSuccess = result?.success === true;
  const isDone = verifyMutation.isSuccess || verifyMutation.isError;

  return (
    <div className="p-5 space-y-5">
      <div>
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Verifying Configuration
        </h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Running a final audio push with the saved settings.
        </p>
      </div>

      {/* Loading state */}
      {verifyMutation.isPending && (
        <SpinnerBlock label="Sending final verification push…" />
      )}

      {/* Success banner */}
      {isDone && isSuccess && (
        <div className="flex items-start gap-3 rounded-xl bg-green-50 p-5 dark:bg-green-950/20">
          <CheckCircle className="mt-0.5 h-7 w-7 flex-shrink-0 text-green-600 dark:text-green-400" />
          <div>
            <p className="text-base font-bold text-green-800 dark:text-green-300">
              Camera is ready!
            </p>
            <p className="mt-0.5 text-sm text-green-600 dark:text-green-500">
              {result?.message ?? `${cameraName} is now enrolled and monitoring.`}
            </p>
          </div>
        </div>
      )}

      {/* Failure banner */}
      {isDone && !isSuccess && (
        <div className="rounded-xl bg-amber-50 p-4 dark:bg-amber-950/20 space-y-3">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-600 dark:text-amber-400" />
            <div>
              <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">
                Verification push did not confirm audio
              </p>
              <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-400">
                {result?.message ?? 'The configuration was saved but the verification push returned an error.'}
              </p>
            </div>
          </div>
          <ul className="space-y-1 pl-2 text-xs text-amber-700 dark:text-amber-400 list-disc list-inside">
            <li>Check that go2rtc can reach the camera stream.</li>
            <li>Verify the camera speaker is not muted in the camera's web UI.</li>
            <li>Try increasing the warmup delay in the camera config.</li>
            <li>Confirm the selected codec matches what the camera advertises.</li>
          </ul>
        </div>
      )}

      {/* Action buttons — always shown when done */}
      {isDone && (
        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            onClick={onFinish}
            className={cn(
              'flex flex-1 items-center justify-center gap-2 rounded-xl px-4 py-3.5 text-sm font-semibold text-white',
              'active:scale-[0.98] transition-all focus:outline-none focus:ring-2 focus:ring-blue-500',
              isSuccess ? 'bg-blue-600 hover:bg-blue-700' : 'bg-gray-600 hover:bg-gray-700',
            )}
          >
            <CheckCircle className="h-4 w-4" />
            Finish
          </button>

          <button
            onClick={onSetupAnother}
            className={cn(
              'flex flex-1 items-center justify-center gap-2 rounded-xl border border-gray-300 bg-white px-4 py-3.5 text-sm font-semibold text-gray-700',
              'hover:bg-gray-50 active:scale-[0.98] transition-all',
              'focus:outline-none focus:ring-2 focus:ring-blue-500',
              'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700',
            )}
          >
            <Camera className="h-4 w-4" />
            Set Up Another Camera
          </button>
        </div>
      )}
    </div>
  );
}
