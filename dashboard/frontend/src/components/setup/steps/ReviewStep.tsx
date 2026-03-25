/**
 * ReviewStep — final confirmation before writing config.yaml.
 *
 * Shows a human-readable summary of every setting the user configured
 * across the wizard steps. The single primary action is
 * "Generate Config & Start VoxWatch".
 *
 * During generation a loading state disables the button. On success
 * a 5-second countdown is shown before navigating to the dashboard.
 * On error an inline error message is displayed so the user can
 * go back and fix the issue.
 */

import { useState, useEffect } from 'react';
import {
  CheckCircle,
  Loader,
  XCircle,
  Server,
  Radio,
  Brain,
  Volume2,
  Mic,
  Camera,
  Shield,
  Minus,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { cn } from '@/utils/cn';
import { generateConfig } from '@/api/setup';
import type { SetupState } from '../useSetupState';

/** Props for ReviewStep. */
interface ReviewStepProps {
  state: SetupState;
}

/** A single row in the review summary table. */
function ReviewRow({
  icon: Icon,
  label,
  value,
  status = 'ok',
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  /** ok = green check, warn = amber X, neutral = grey dash (no probe done) */
  status?: 'ok' | 'warn' | 'neutral';
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg px-4 py-3 bg-gray-800/40">
      <Icon className="h-4 w-4 shrink-0 text-gray-500" />
      <span className="w-32 shrink-0 text-sm text-gray-400">{label}</span>
      <span className="flex-1 text-sm font-medium text-gray-200 truncate">{value}</span>
      {status === 'ok' && <CheckCircle className="h-4 w-4 shrink-0 text-green-400" />}
      {status === 'warn' && <XCircle className="h-4 w-4 shrink-0 text-amber-400" />}
      {status === 'neutral' && <Minus className="h-4 w-4 shrink-0 text-gray-600" />}
    </div>
  );
}

/**
 * Setup review and config generation step.
 *
 * @example
 *   <ReviewStep state={setupState} />
 */
export function ReviewStep({ state }: ReviewStepProps) {
  const navigate = useNavigate();
  const [countdown, setCountdown] = useState<number | null>(null);

  const enabledCameras = Object.entries(state.selectedCameras).filter(([, v]) => v.enabled);

  const generateMutation = useMutation({
    mutationFn: () =>
      generateConfig({
        frigate_host: state.frigateHost,
        frigate_port: state.frigatePort,
        go2rtc_host: state.go2rtcHost || state.frigateHost,
        go2rtc_port: state.go2rtcPort,
        mqtt_host: state.mqttHost || state.frigateHost,
        mqtt_port: state.mqttPort,
        mqtt_user: state.mqttUser,
        mqtt_password: state.mqttPassword,
        mqtt_topic: state.mqttTopic,
        ai_provider: state.aiProvider,
        ai_model: state.aiModel,
        ai_api_key: state.aiApiKey,
        tts_engine: state.ttsEngine,
        tts_voice: state.ttsVoice,
        // Provider-specific TTS config: API keys and Kokoro host
        tts_api_key: state.ttsProviderConfig.api_key ?? '',
        tts_host: state.ttsProviderConfig.kokoro_host ?? '',
        response_mode: state.responseMode,
        cameras: state.selectedCameras,
      }),
    onSuccess: () => {
      setCountdown(5);
    },
  });

  // Countdown and navigation after success
  useEffect(() => {
    if (countdown === null) return;
    if (countdown === 0) {
      navigate('/');
      return;
    }
    const timer = setTimeout(() => setCountdown((c) => (c ?? 1) - 1), 1000);
    return () => clearTimeout(timer);
  }, [countdown, navigate]);

  const aiLabel =
    state.aiProvider === 'none'
      ? 'Skipped'
      : `${state.aiProvider} / ${state.aiModel}`;

  const ttsLabel = `${state.ttsEngine} — ${state.ttsVoice}`;

  // Format response mode name for display
  const responseLabel = state.responseMode
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');

  return (
    <div className="space-y-6 px-6 py-8">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-gray-100">Review your setup</h2>
        <p className="mt-1 text-sm text-gray-400">
          Everything looks good. Click below to write your configuration file and start VoxWatch.
        </p>
      </div>

      {/* Summary table */}
      <div className="space-y-2">
        <ReviewRow
          icon={Server}
          label="Frigate"
          value={`${state.frigateHost}:${state.frigatePort}`}
          status={state.probeResult?.frigate_reachable ? 'ok' : 'warn'}
        />
        <ReviewRow
          icon={Server}
          label="go2rtc"
          value={`${state.go2rtcHost || state.frigateHost}:${state.go2rtcPort}`}
          status={state.probeResult?.go2rtc_reachable ? 'ok' : 'warn'}
        />
        {/*
          MQTT: show the user-entered host:port with a neutral (no status)
          indicator. The probe result may be stale — the user may have changed
          the MQTT host on the MQTT step after the initial probe. VoxWatch will
          validate MQTT on first startup using whatever values are written here.
        */}
        <ReviewRow
          icon={Radio}
          label="MQTT"
          value={`${state.mqttHost || state.frigateHost}:${state.mqttPort}`}
          status="neutral"
        />
        <ReviewRow
          icon={Brain}
          label="AI provider"
          value={aiLabel}
          status={state.aiProvider === 'none' ? 'warn' : 'ok'}
        />
        <ReviewRow
          icon={Volume2}
          label="TTS engine"
          value={ttsLabel}
          status="ok"
        />
        <ReviewRow
          icon={Mic}
          label="Response mode"
          value={responseLabel}
          status="ok"
        />
        <ReviewRow
          icon={Camera}
          label="Cameras"
          value={`${enabledCameras.length} enabled: ${enabledCameras.map(([n]) => n).join(', ')}`}
          status={enabledCameras.length > 0 ? 'ok' : 'warn'}
        />
      </div>

      {/* Success state */}
      {generateMutation.isSuccess && countdown !== null && (
        <div className="flex flex-col items-center gap-3 rounded-xl bg-green-900/20 border border-green-700/50 px-4 py-6 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-green-500/20">
            <Shield className="h-7 w-7 text-green-400" />
          </div>
          <p className="text-lg font-bold text-green-300">VoxWatch is starting!</p>
          <p className="text-sm text-green-500">
            Redirecting to dashboard in {countdown}s...
          </p>
          <button
            onClick={() => navigate('/')}
            className="text-sm text-green-400 underline hover:text-green-300"
          >
            Go now
          </button>
        </div>
      )}

      {/* Error state */}
      {generateMutation.isError && (
        <div className="flex items-start gap-3 rounded-xl bg-red-950/40 border border-red-800/50 px-4 py-3 text-sm text-red-300">
          <XCircle className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p className="font-semibold">Config generation failed</p>
            <p className="mt-0.5 text-xs opacity-80">
              {(generateMutation.error as Error)?.message ?? 'An unexpected error occurred. Check the backend logs.'}
            </p>
          </div>
        </div>
      )}

      {/* Generate button (hidden after success) */}
      {!generateMutation.isSuccess && (
        <button
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending || enabledCameras.length === 0}
          className={cn(
            'flex w-full items-center justify-center gap-3 rounded-xl px-6 py-5',
            'text-base font-bold text-white',
            'transition-all duration-150 active:scale-[0.98]',
            'focus:outline-none focus:ring-2 focus:ring-blue-400',
            'disabled:cursor-not-allowed disabled:opacity-40',
            generateMutation.isPending
              ? 'bg-blue-700'
              : 'bg-blue-600 hover:bg-blue-500 shadow-[0_0_20px_rgba(59,130,246,0.3)]',
          )}
        >
          {generateMutation.isPending ? (
            <>
              <Loader className="h-5 w-5 animate-spin" />
              Generating config...
            </>
          ) : (
            <>
              <Shield className="h-5 w-5" />
              Generate Config & Start VoxWatch
            </>
          )}
        </button>
      )}
    </div>
  );
}
