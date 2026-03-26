/**
 * DiscoveryStep — shows the results of the service probe.
 *
 * Renders a status card for each discovered service:
 *   - Frigate:  connected, camera count, version
 *   - go2rtc:   connected or with an override input when not found
 *   - MQTT:     connected or with override input when not found
 *
 * Also renders a camera grid with backchannel badges so users immediately
 * see which cameras have speakers.
 *
 * "Continue" is enabled once at least Frigate is reachable.
 */

import { useState } from 'react';
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Video,
  Mic,
  MicOff,
  ArrowRight,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import type { ProbeResult } from '@/api/setup';

/** Props for DiscoveryStep. */
interface DiscoveryStepProps {
  /** Full probe result from the backend. */
  probeResult: ProbeResult;
  /** Current go2rtc host value (may differ from probe if user overrides). */
  go2rtcHost: string;
  /** Current go2rtc port value. */
  go2rtcPort: number;
  /** Current MQTT host value. */
  mqttHost: string;
  /** Current MQTT port value. */
  mqttPort: number;
  /** Called when the user updates go2rtc settings. */
  onGo2rtcChange: (host: string, port: number) => void;
  /** Called when the user updates MQTT host/port overrides on this screen. */
  onMqttHostChange: (host: string, port: number) => void;
  /** Called when the user clicks Continue. */
  onNext: () => void;
}

/** Visual badge for backchannel status. */
function BackchannelBadge({ hasBackchannel }: { hasBackchannel: boolean | undefined }) {
  if (hasBackchannel === undefined) {
    return (
      <span className="rounded-full bg-gray-700 px-2 py-0.5 text-[11px] font-medium text-gray-400">
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
    <span className="flex items-center gap-1 rounded-full bg-gray-800 px-2 py-0.5 text-[11px] font-medium text-gray-500 border border-gray-700/50">
      <MicOff className="h-3 w-3" />
      No speaker
    </span>
  );
}

/** Single service status row. */
function ServiceRow({
  label,
  reachable,
  detail,
  children,
}: {
  label: string;
  reachable: boolean;
  detail?: string | undefined;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-gray-700/50 bg-gray-800/50 px-4 py-3">
      {reachable ? (
        <CheckCircle className="mt-0.5 h-5 w-5 shrink-0 text-green-400" />
      ) : (
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
      )}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-gray-200">{label}</p>
        {detail && (
          <p className="mt-0.5 text-xs text-gray-400">{detail}</p>
        )}
        {children}
      </div>
    </div>
  );
}

const inputCls = cn(
  'w-full rounded-lg border bg-gray-800 px-3 py-2 text-sm text-gray-100',
  'border-gray-600 placeholder-gray-500',
  'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50',
  'transition-colors',
);

/**
 * Discovery results page showing probe outcome for all three services.
 *
 * @example
 *   <DiscoveryStep probeResult={result} go2rtcHost="192.168.1.10" ... />
 */
export function DiscoveryStep({
  probeResult,
  go2rtcHost,
  go2rtcPort,
  mqttHost,
  mqttPort,
  onGo2rtcChange,
  onMqttHostChange,
  onNext,
}: DiscoveryStepProps) {
  const [showCameras, setShowCameras] = useState(true);

  const frigateDetail = probeResult.frigate_reachable
    ? `Connected · Frigate ${probeResult.frigate_version ?? 'unknown'} · ${probeResult.frigate_cameras.length} camera${probeResult.frigate_cameras.length !== 1 ? 's' : ''} found`
    : probeResult.errors['frigate'] ?? 'Could not reach Frigate API';

  const go2rtcDetail = probeResult.go2rtc_reachable
    ? `Connected · go2rtc ${probeResult.go2rtc_version ?? 'unknown'} · ${probeResult.go2rtc_streams.length} stream${probeResult.go2rtc_streams.length !== 1 ? 's' : ''}`
    : probeResult.errors['go2rtc'] ?? 'go2rtc not found at default address';

  const mqttDetail = probeResult.mqtt_reachable
    ? 'MQTT broker connected'
    : probeResult.errors['mqtt'] ?? 'Could not connect to MQTT broker';

  return (
    <div className="space-y-5 px-6 py-8">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-gray-100">Services discovered</h2>
        <p className="mt-1 text-sm text-gray-400">
          VoxWatch probed your network in {probeResult.probe_duration_ms}ms.
        </p>
      </div>

      {/* Service status cards */}
      <div className="space-y-3">
        {/* Frigate */}
        <ServiceRow
          label="Frigate NVR"
          reachable={probeResult.frigate_reachable}
          detail={frigateDetail}
        />

        {/* go2rtc */}
        <ServiceRow
          label="go2rtc (audio push)"
          reachable={probeResult.go2rtc_reachable}
          detail={probeResult.go2rtc_reachable ? go2rtcDetail : undefined}
        >
          {!probeResult.go2rtc_reachable && (
            <div className="mt-2 space-y-1">
              <p className="text-xs text-amber-400">{go2rtcDetail}</p>
              <p className="text-xs text-gray-500">
                Override the address if go2rtc runs on a different host.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={go2rtcHost}
                  onChange={(e) => onGo2rtcChange(e.target.value, go2rtcPort)}
                  placeholder="hostname or IP"
                  className={cn(inputCls, 'flex-1')}
                />
                <input
                  type="number"
                  value={go2rtcPort}
                  onChange={(e) => onGo2rtcChange(go2rtcHost, Number(e.target.value))}
                  min={1}
                  max={65535}
                  className={cn(inputCls, 'w-20')}
                />
              </div>
            </div>
          )}
        </ServiceRow>

        {/* MQTT */}
        <ServiceRow
          label="MQTT broker"
          reachable={probeResult.mqtt_reachable}
          detail={probeResult.mqtt_reachable ? mqttDetail : undefined}
        >
          {!probeResult.mqtt_reachable && (
            <div className="mt-2 space-y-1">
              <p className="text-xs text-amber-400">{mqttDetail}</p>
              <p className="text-xs text-gray-500">
                Override if MQTT runs separately (common with external brokers).
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={mqttHost}
                  onChange={(e) => onMqttHostChange(e.target.value, mqttPort)}
                  placeholder="hostname or IP"
                  className={cn(inputCls, 'flex-1')}
                />
                <input
                  type="number"
                  value={mqttPort}
                  onChange={(e) => onMqttHostChange(mqttHost, Number(e.target.value))}
                  min={1}
                  max={65535}
                  className={cn(inputCls, 'w-20')}
                />
              </div>
            </div>
          )}
        </ServiceRow>
      </div>

      {/* Camera grid */}
      {probeResult.frigate_cameras.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowCameras((v) => !v)}
            className="flex items-center gap-2 text-sm font-semibold text-gray-300 hover:text-gray-100 transition-colors focus:outline-none"
          >
            <Video className="h-4 w-4 text-blue-400" />
            {probeResult.frigate_cameras.length} camera{probeResult.frigate_cameras.length !== 1 ? 's' : ''} found
            {showCameras ? (
              <ChevronUp className="h-4 w-4 text-gray-500" />
            ) : (
              <ChevronDown className="h-4 w-4 text-gray-500" />
            )}
          </button>

          {showCameras && (
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {probeResult.frigate_cameras.map((cam) => {
                const info = probeResult.backchannel_info[cam];
                return (
                  <div
                    key={cam}
                    className="flex flex-col gap-1.5 rounded-xl border border-gray-700/50 bg-gray-800/30 px-3 py-3"
                  >
                    <span className="text-sm font-medium text-gray-200 truncate">{cam}</span>
                    <BackchannelBadge hasBackchannel={info?.has_backchannel} />
                    {info?.codecs && info.codecs.length > 0 && (
                      <span className="text-[10px] text-gray-500 font-mono">
                        {/* Show only the recommended codec, not the full list */}
                        {info.codecs.find((c: string) => c.includes('PCMU') || c.includes('PCMA'))
                          ?? info.codecs[0]}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Frigate not reachable — can't continue */}
      {!probeResult.frigate_reachable && (
        <div className="flex items-start gap-2 rounded-lg bg-red-950/40 px-4 py-3 text-sm text-red-300 border border-red-800/50">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Frigate must be reachable to continue. Check the hostname and try again from the previous step.
          </span>
        </div>
      )}

      {/* Continue */}
      <button
        onClick={onNext}
        disabled={!probeResult.frigate_reachable}
        className={cn(
          'flex w-full items-center justify-center gap-3 rounded-xl px-6 py-4',
          'text-base font-semibold text-white',
          'transition-all duration-150 active:scale-[0.98]',
          'focus:outline-none focus:ring-2 focus:ring-blue-400',
          'disabled:cursor-not-allowed disabled:opacity-40',
          probeResult.frigate_reachable
            ? 'bg-blue-600 hover:bg-blue-500'
            : 'bg-gray-700',
        )}
      >
        Continue
        <ArrowRight className="h-5 w-5" />
      </button>
    </div>
  );
}
