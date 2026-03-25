/**
 * CameraSelectStep — select which cameras VoxWatch should protect.
 *
 * Renders cameras in three grouped sections:
 *   1. Compatible (Speaker Confirmed) — cameras whose backchannel is present in
 *      the go2rtc probe AND whose codec list contains a preferred PCMU/PCMA entry.
 *   2. No Speaker Detected — backchannel absent in the probe data.
 *   3. Unknown — Try in Dashboard — cameras present in Frigate but absent from
 *      go2rtc (no backchannel info available at all).
 *
 * The raw codec list is hidden. Instead the first PCMU or PCMA codec is shown
 * as a subtle "Recommended codec" label so the UI stays clean.
 *
 * The Test Audio button has been removed from the wizard step — it requires
 * config.yaml which does not exist yet. A note directs the user to test from
 * the Camera Setup page once setup is complete.
 *
 * Cameras with a confirmed backchannel are pre-checked. At least one camera
 * must be selected to proceed.
 */

import {
  Camera,
  Mic,
  MicOff,
  HelpCircle,
  ArrowRight,
  AlertTriangle,
} from 'lucide-react';
import { cn } from '@/utils/cn';
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Pick the first PCMU or PCMA codec from a list, falling back to the first
 * codec in the list if neither preferred codec is present.
 *
 * @param codecs - Array of raw codec strings from the go2rtc backchannel probe.
 * @returns Recommended codec string, or undefined when the list is empty.
 */
function pickRecommendedCodec(codecs: string[]): string | undefined {
  if (codecs.length === 0) return undefined;
  const preferred = codecs.find((c) => c.startsWith('PCMU') || c.startsWith('PCMA'));
  return preferred ?? codecs[0];
}

// ---------------------------------------------------------------------------
// Section badge components
// ---------------------------------------------------------------------------

/** Badge for a confirmed speaker camera. */
function ConfirmedBadge() {
  return (
    <span className="flex items-center gap-1 rounded-full bg-green-900/50 px-2 py-0.5 text-[11px] font-medium text-green-400 border border-green-700/50">
      <Mic className="h-3 w-3" />
      Speaker
    </span>
  );
}

/** Badge for a camera with no detected speaker. */
function NoSpeakerBadge() {
  return (
    <span className="flex items-center gap-1 rounded-full bg-gray-800 px-2 py-0.5 text-[11px] font-medium text-gray-500 border border-gray-700/40">
      <MicOff className="h-3 w-3" />
      No speaker
    </span>
  );
}

/** Badge for a camera with unknown backchannel support. */
function UnknownBadge() {
  return (
    <span className="flex items-center gap-1 rounded-full bg-gray-700 px-2 py-0.5 text-[11px] font-medium text-gray-400">
      <HelpCircle className="h-3 w-3" />
      Unknown
    </span>
  );
}

// ---------------------------------------------------------------------------
// Camera card
// ---------------------------------------------------------------------------

interface CameraCardProps {
  camName: string;
  badge: React.ReactNode;
  recommendedCodec: string | undefined;
  camState: { enabled: boolean; go2rtc_stream: string; audio_codec?: string };
  onCameraToggle: (name: string, enabled: boolean) => void;
  onStreamChange: (name: string, stream: string) => void;
}

/**
 * Single camera row card with checkbox, name, badge, codec label, and stream
 * name override. Test audio button is intentionally absent — it requires a
 * config.yaml that does not exist during setup.
 */
function CameraCard({
  camName,
  badge,
  recommendedCodec,
  camState,
  onCameraToggle,
  onStreamChange,
}: CameraCardProps) {
  const isEnabled = camState.enabled;

  return (
    <div
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
        {badge}
      </div>

      {/* Recommended codec label — subtle, single codec only */}
      {recommendedCodec && (
        <p className="mt-1 ml-8 text-[11px] font-mono text-gray-600">
          {recommendedCodec}
        </p>
      )}

      {/* go2rtc stream name override — shown only when camera is enabled */}
      {isEnabled && (
        <div className="mt-3 ml-8">
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
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section heading
// ---------------------------------------------------------------------------

interface SectionHeadingProps {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  count: number;
}

function SectionHeading({ icon, title, subtitle, count }: SectionHeadingProps) {
  return (
    <div className="flex items-start gap-2 mb-2">
      <span className="mt-0.5">{icon}</span>
      <div>
        <p className="text-sm font-semibold text-gray-300">
          {title}
          <span className="ml-1.5 text-xs font-normal text-gray-600">
            ({count})
          </span>
        </p>
        <p className="text-xs text-gray-600">{subtitle}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CameraSelectStep
// ---------------------------------------------------------------------------

/**
 * Camera selection step grouped by speaker compatibility.
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
  const enabledCount = Object.values(selectedCameras).filter((c) => c.enabled).length;

  // ---------------------------------------------------------------------------
  // Group cameras into three sections.
  //
  // "Compatible" — has_backchannel === true in the go2rtc probe.
  // "No speaker" — has_backchannel === false in the go2rtc probe.
  // "Unknown"    — camera name is in Frigate but not in go2rtc streams
  //                (backchannel_info key absent entirely).
  // ---------------------------------------------------------------------------

  const compatible: string[] = [];
  const noSpeaker: string[] = [];
  const unknown: string[] = [];

  for (const camName of probeResult.frigate_cameras) {
    const info = probeResult.backchannel_info[camName];
    if (info === undefined) {
      // Camera known to Frigate but go2rtc has no backchannel data for it.
      unknown.push(camName);
    } else if (info.has_backchannel) {
      compatible.push(camName);
    } else {
      noSpeaker.push(camName);
    }
  }

  /**
   * Render one camera card, resolving state and picking the recommended codec.
   */
  const renderCard = (camName: string, badge: React.ReactNode) => {
    const camState = selectedCameras[camName] ?? {
      enabled: false,
      go2rtc_stream: camName,
    };
    const codecs = probeResult.backchannel_info[camName]?.codecs ?? [];
    const recommendedCodec = pickRecommendedCodec(codecs);

    return (
      <CameraCard
        key={camName}
        camName={camName}
        badge={badge}
        recommendedCodec={recommendedCodec}
        camState={camState}
        onCameraToggle={onCameraToggle}
        onStreamChange={onStreamChange}
      />
    );
  };

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
            Cameras grouped by backchannel detection from go2rtc.
          </p>
        </div>
      </div>

      {/* No cameras at all */}
      {probeResult.frigate_cameras.length === 0 && (
        <div className="rounded-xl bg-amber-950/40 border border-amber-800/50 px-4 py-3 text-sm text-amber-300">
          No cameras were found in Frigate. Configure cameras in Frigate before proceeding.
        </div>
      )}

      {/* Section 1: Compatible */}
      {compatible.length > 0 && (
        <div className="space-y-2">
          <SectionHeading
            icon={<Mic className="h-4 w-4 text-green-500" />}
            title="Compatible (Speaker Confirmed)"
            subtitle="Backchannel detected — these cameras should be able to play audio."
            count={compatible.length}
          />
          {compatible.map((n) => renderCard(n, <ConfirmedBadge />))}
        </div>
      )}

      {/* Section 2: No Speaker */}
      {noSpeaker.length > 0 && (
        <div className="space-y-2">
          <SectionHeading
            icon={<MicOff className="h-4 w-4 text-gray-500" />}
            title="No Speaker Detected"
            subtitle="No backchannel found in go2rtc. These cameras likely have no speaker."
            count={noSpeaker.length}
          />
          {noSpeaker.map((n) => renderCard(n, <NoSpeakerBadge />))}
        </div>
      )}

      {/* Section 3: Unknown */}
      {unknown.length > 0 && (
        <div className="space-y-2">
          <SectionHeading
            icon={<HelpCircle className="h-4 w-4 text-gray-500" />}
            title="Unknown — Try in Dashboard"
            subtitle="Not found in go2rtc streams. Enable and verify audio manually after setup."
            count={unknown.length}
          />
          {unknown.map((n) => renderCard(n, <UnknownBadge />))}
        </div>
      )}

      {/* Speaker detection accuracy note */}
      <div className="flex items-start gap-2 rounded-xl bg-gray-800/60 border border-gray-700/40 px-4 py-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        <p className="text-xs text-gray-500 leading-relaxed">
          Speaker detection is based on RTSP backchannel data from go2rtc. Some cameras
          advertise backchannel without a built-in speaker (e.g. external RCA output).
          Audio testing is available after setup completes in the Camera Setup page.
        </p>
      </div>

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
