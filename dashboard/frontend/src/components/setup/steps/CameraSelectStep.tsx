/**
 * CameraSelectStep — select which cameras VoxWatch should protect.
 *
 * Renders a grid of camera cards sourced from the probeResult.frigate_cameras list.
 * Each card shows:
 *   - Camera name
 *   - Backchannel badge (green = speaker detected, amber = unknown, gray = no speaker)
 *   - Recommended codec from the probe
 *   - go2rtc stream assignment (auto-matched from probe, user can edit)
 *   - Test Audio button that pushes a live test clip to the camera speaker
 *
 * Cameras with detected backchannels are pre-checked. The user must select
 * at least one camera to proceed.
 *
 * The go2rtc stream name defaults to the camera name (Frigate and go2rtc stream
 * names typically match). If the names diverge the user can correct them here.
 */

import { useState } from 'react';
import {
  Camera,
  Mic,
  MicOff,
  HelpCircle,
  Play,
  Loader,
  CheckCircle,
  XCircle,
  ArrowRight,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { testAudio } from '@/api/audio';
import type { ProbeResult } from '@/api/setup';

/** Props for CameraSelectStep. */
interface CameraSelectStepProps {
  probeResult: ProbeResult;
  selectedCameras: Record<string, { enabled: boolean; go2rtc_stream: string; audio_codec?: string }>;
  onCameraToggle: (name: string, enabled: boolean) => void;
  onStreamChange: (name: string, stream: string) => void;
  onNext: () => void;
}

const inputCls = cn(
  'w-full rounded-md border bg-gray-900 px-2 py-1.5 text-sm text-gray-200',
  'border-gray-600 placeholder-gray-600',
  'focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50',
);

/** Badge showing backchannel / speaker status. */
function BackchannelBadge({ hasBackchannel }: { hasBackchannel: boolean | undefined }) {
  if (hasBackchannel === undefined) {
    return (
      <span className="flex items-center gap-1 rounded-full bg-gray-700 px-2 py-0.5 text-[11px] font-medium text-gray-400">
        <HelpCircle className="h-3 w-3" />
        Unknown
      </span>
    );
  }
  return hasBackchannel ? (
    <span className="flex items-center gap-1 rounded-full bg-green-900/50 px-2 py-0.5 text-[11px] font-medium text-green-400 border border-green-700/50">
      <Mic className="h-3 w-3" />
      Speaker
    </span>
  ) : (
    <span className="flex items-center gap-1 rounded-full bg-gray-800 px-2 py-0.5 text-[11px] font-medium text-gray-500 border border-gray-700/40">
      <MicOff className="h-3 w-3" />
      No speaker
    </span>
  );
}

/**
 * Camera selection grid with per-camera stream and audio test controls.
 *
 * @example
 *   <CameraSelectStep probeResult={result} selectedCameras={{}} ... />
 */
export function CameraSelectStep({
  probeResult,
  selectedCameras,
  onCameraToggle,
  onStreamChange,
  onNext,
}: CameraSelectStepProps) {
  // Track which camera is being tested right now
  const [testingCamera, setTestingCamera] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({});

  const testMutation = useMutation({
    mutationFn: (cameraName: string) =>
      testAudio({ camera_name: cameraName }),
    onSuccess: (data, cameraName) => {
      setTestResults((prev) => ({
        ...prev,
        [cameraName]: { success: data.success, message: data.message },
      }));
      setTestingCamera(null);
    },
    onError: (_err, cameraName) => {
      setTestResults((prev) => ({
        ...prev,
        [cameraName]: { success: false, message: 'Failed to reach backend' },
      }));
      setTestingCamera(null);
    },
  });

  const handleTest = (cameraName: string) => {
    setTestingCamera(cameraName);
    testMutation.mutate(cameraName);
  };

  const enabledCount = Object.values(selectedCameras).filter((c) => c.enabled).length;

  return (
    <div className="space-y-6 px-6 py-8">
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600/20 text-blue-400">
          <Camera className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-100">Select cameras to protect</h2>
          <p className="mt-1 text-sm text-gray-400">
            VoxWatch will speak through these cameras when people are detected.
            Cameras with a speaker badge already have audio output confirmed.
          </p>
        </div>
      </div>

      {/* Camera grid */}
      <div className="space-y-3">
        {probeResult.frigate_cameras.map((camName) => {
          const camState = selectedCameras[camName] ?? { enabled: false, go2rtc_stream: camName };
          const backchannelInfo = probeResult.backchannel_info[camName];
          const isEnabled = camState.enabled;
          const isTesting = testingCamera === camName;
          const testResult = testResults[camName];

          return (
            <div
              key={camName}
              className={cn(
                'rounded-xl border p-4 transition-colors',
                isEnabled
                  ? 'border-blue-700/50 bg-blue-900/10'
                  : 'border-gray-700/50 bg-gray-800/30',
              )}
            >
              {/* Top row: checkbox + name + badge */}
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id={`cam-${camName}`}
                  checked={isEnabled}
                  onChange={(e) => onCameraToggle(camName, e.target.checked)}
                  className={cn(
                    'h-5 w-5 rounded border-gray-600 bg-gray-800',
                    'accent-blue-500 cursor-pointer',
                    'focus:ring-2 focus:ring-blue-500 focus:ring-offset-gray-900',
                  )}
                />
                <label
                  htmlFor={`cam-${camName}`}
                  className="flex-1 cursor-pointer text-sm font-semibold text-gray-200"
                >
                  {camName}
                </label>
                <BackchannelBadge hasBackchannel={backchannelInfo?.has_backchannel} />
              </div>

              {/* Codec info */}
              {backchannelInfo?.codecs && backchannelInfo.codecs.length > 0 && (
                <p className="mt-1.5 ml-8 text-[11px] font-mono text-gray-500">
                  {backchannelInfo.codecs.join(' · ')}
                </p>
              )}

              {/* go2rtc stream override + test button — shown when enabled */}
              {isEnabled && (
                <div className="mt-3 ml-8 flex items-center gap-2">
                  <div className="flex-1">
                    <label className="mb-1 block text-[11px] text-gray-500">
                      go2rtc stream name
                    </label>
                    <input
                      type="text"
                      value={camState.go2rtc_stream}
                      onChange={(e) => onStreamChange(camName, e.target.value)}
                      placeholder={camName}
                      className={inputCls}
                    />
                  </div>

                  {/* Test audio button */}
                  <div className="pt-5">
                    <button
                      type="button"
                      onClick={() => handleTest(camName)}
                      disabled={isTesting}
                      title="Test audio push to this camera"
                      className={cn(
                        'flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold',
                        'border transition-all active:scale-95',
                        'focus:outline-none focus:ring-2 focus:ring-blue-500',
                        'disabled:cursor-not-allowed disabled:opacity-50',
                        testResult?.success
                          ? 'border-green-700 bg-green-900/20 text-green-300'
                          : testResult && !testResult.success
                            ? 'border-red-700 bg-red-950/20 text-red-300'
                            : 'border-gray-600 bg-gray-800 text-gray-400 hover:text-gray-200 hover:border-gray-500',
                      )}
                    >
                      {isTesting ? (
                        <Loader className="h-3.5 w-3.5 animate-spin" />
                      ) : testResult?.success ? (
                        <CheckCircle className="h-3.5 w-3.5" />
                      ) : testResult && !testResult.success ? (
                        <XCircle className="h-3.5 w-3.5" />
                      ) : (
                        <Play className="h-3.5 w-3.5" />
                      )}
                      {isTesting ? 'Testing...' : 'Test'}
                    </button>
                  </div>
                </div>
              )}

              {/* Test result message */}
              {testResult && isEnabled && (
                <p className={cn(
                  'mt-2 ml-8 text-xs',
                  testResult.success ? 'text-green-500' : 'text-red-400',
                )}>
                  {testResult.message}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* No cameras warning */}
      {probeResult.frigate_cameras.length === 0 && (
        <div className="rounded-xl bg-amber-950/40 border border-amber-800/50 px-4 py-3 text-sm text-amber-300">
          No cameras were found in Frigate. Make sure cameras are configured in Frigate before proceeding.
        </div>
      )}

      {/* Summary */}
      <p className="text-sm text-gray-500">
        {enabledCount === 0
          ? 'Select at least one camera to continue.'
          : `${enabledCount} camera${enabledCount !== 1 ? 's' : ''} selected.`}
      </p>

      {/* Continue */}
      <button
        onClick={onNext}
        disabled={enabledCount === 0}
        className={cn(
          'flex w-full items-center justify-center gap-3 rounded-xl px-6 py-4',
          'text-base font-semibold text-white',
          'transition-all duration-150 active:scale-[0.98]',
          'focus:outline-none focus:ring-2 focus:ring-blue-400',
          'disabled:cursor-not-allowed disabled:opacity-40',
          enabledCount > 0 ? 'bg-blue-600 hover:bg-blue-500' : 'bg-gray-700',
        )}
      >
        Continue
        <ArrowRight className="h-5 w-5" />
      </button>
    </div>
  );
}
