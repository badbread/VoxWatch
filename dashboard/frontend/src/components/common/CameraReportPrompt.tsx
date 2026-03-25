/**
 * CameraReportPrompt — reusable card that invites the user to report a camera
 * compatibility result to the VoxWatch community via a GitHub issue.
 *
 * Shown after an audio test completes on a camera that is NOT already in the
 * VoxWatch camera database. Uses a thank-you tone, not a demand. The "Report
 * Results" button opens a pre-filled GitHub issue form in a new tab so the
 * user only has to review and submit.
 *
 * Visual treatment:
 *   - Green accent for successful tests (audio heard clearly).
 *   - Amber accent for failed/garbled/partial tests.
 *
 * Usage:
 *   <CameraReportPrompt
 *     cameraName="frontdoor"
 *     manufacturer="Reolink"
 *     model="CX410"
 *     firmware="v3.2.0.4741"
 *     backchannelCodecs={["PCMU/8000"]}
 *     hasBackchannel={true}
 *     audioResult="success"
 *     frigateVersion="0.14.1"
 *     go2rtcVersion="1.9.4"
 *     onDismiss={() => setPromptDismissed(true)}
 *   />
 */

import { useState } from 'react';
import { ExternalLink, Heart, AlertTriangle, X } from 'lucide-react';
import { cn } from '@/utils/cn';
import { buildCameraReportUrl } from '@/utils/cameraReport';

/** VoxWatch dashboard version — hardcoded here, matches pyproject.toml. */
const VOXWATCH_VERSION = '1.0.0';

export interface CameraReportPromptProps {
  /** Frigate camera name (used for display only). */
  cameraName: string;
  /** Manufacturer string from ONVIF identification. */
  manufacturer?: string | undefined;
  /** Model string from ONVIF identification. */
  model?: string | undefined;
  /** Firmware version from ONVIF identification. */
  firmware?: string | undefined;
  /** Camera IP address from ONVIF probe. */
  ip?: string | undefined;
  /** Raw backchannel codec strings from go2rtc. */
  backchannelCodecs?: string[] | undefined;
  /** Whether go2rtc detected a backchannel track. */
  hasBackchannel?: boolean | undefined;
  /** Self-reported outcome of the audio test. */
  audioResult: 'success' | 'failed' | 'garbled' | 'partial';
  /** Frigate version from status API — injected by the parent. */
  frigateVersion?: string | undefined;
  /** go2rtc version from status API — injected by the parent. */
  go2rtcVersion?: string | undefined;
  /** Called when the user clicks "Maybe Later". */
  onDismiss?: (() => void) | undefined;
}

/**
 * Derives the visual accent colour and copy based on the audio test result.
 *
 * @param result - Audio test outcome.
 * @returns Object with Tailwind class names and human-readable strings.
 */
function resolveVariant(result: CameraReportPromptProps['audioResult']): {
  containerCls: string;
  iconCls: string;
  headingCls: string;
  bodyCls: string;
  buttonCls: string;
  icon: React.ElementType;
  heading: string;
  body: string;
} {
  if (result === 'success') {
    return {
      containerCls:
        'border-green-200 bg-green-50 dark:border-green-800/50 dark:bg-green-950/20',
      iconCls: 'text-green-500',
      headingCls: 'text-green-800 dark:text-green-300',
      bodyCls: 'text-green-700 dark:text-green-400',
      buttonCls:
        'bg-green-600 hover:bg-green-700 focus:ring-green-500 text-white',
      icon: Heart,
      heading: 'This camera works! Help the community.',
      body: 'You just confirmed audio on an undocumented camera. Share your results so other VoxWatch users with the same hardware know it works.',
    };
  }

  return {
    containerCls:
      'border-amber-200 bg-amber-50 dark:border-amber-800/50 dark:bg-amber-950/20',
    iconCls: 'text-amber-500',
    headingCls: 'text-amber-800 dark:text-amber-300',
    bodyCls: 'text-amber-700 dark:text-amber-400',
    buttonCls:
      'bg-amber-500 hover:bg-amber-600 focus:ring-amber-400 text-white',
    icon: AlertTriangle,
    heading: 'Audio did not work — your report helps.',
    body: 'Unknown cameras need real-world data to improve compatibility. Filing a report takes 30 seconds and helps the next person avoid hours of debugging.',
  };
}

/**
 * CameraReportPrompt card component.
 *
 * Renders nothing once the user has dismissed it.
 */
export function CameraReportPrompt({
  cameraName,
  manufacturer,
  model,
  firmware,
  ip,
  backchannelCodecs,
  hasBackchannel,
  audioResult,
  frigateVersion,
  go2rtcVersion,
  onDismiss,
}: CameraReportPromptProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const variant = resolveVariant(audioResult);
  const Icon = variant.icon;

  const reportUrl = buildCameraReportUrl({
    manufacturer,
    model,
    firmware,
    ip,
    backchannelCodecs,
    hasBackchannel,
    audioResult,
    frigateVersion,
    go2rtcVersion,
    voxwatchVersion: VOXWATCH_VERSION,
  });

  /** Handle dismiss — call optional parent callback and hide the prompt. */
  const handleDismiss = () => {
    setDismissed(true);
    onDismiss?.();
  };

  return (
    <div
      className={cn(
        'relative rounded-xl border p-4',
        variant.containerCls,
      )}
      role="complementary"
      aria-label={`Camera compatibility report prompt for ${cameraName}`}
    >
      {/* Dismiss (X) button — top-right */}
      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Dismiss report prompt"
        className={cn(
          'absolute right-3 top-3 rounded p-0.5 transition-opacity',
          'opacity-50 hover:opacity-100',
          variant.bodyCls,
          'focus:outline-none focus:ring-2 focus:ring-offset-1',
          variant.buttonCls.includes('green')
            ? 'focus:ring-green-500'
            : 'focus:ring-amber-400',
        )}
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>

      <div className="flex items-start gap-3 pr-6">
        {/* Accent icon */}
        <div className="mt-0.5 flex-shrink-0">
          <Icon className={cn('h-5 w-5', variant.iconCls)} aria-hidden="true" />
        </div>

        <div className="min-w-0 flex-1 space-y-2">
          {/* Heading */}
          <p className={cn('text-sm font-semibold leading-snug', variant.headingCls)}>
            {variant.heading}
          </p>

          {/* Body copy */}
          <p className={cn('text-xs leading-relaxed', variant.bodyCls)}>
            {variant.body}
          </p>

          {/* Camera details line — shows what data will be pre-filled */}
          {(manufacturer || model) && (
            <p className={cn('text-xs font-mono', variant.bodyCls)}>
              {[manufacturer, model].filter(Boolean).join(' ')}
              {firmware ? ` · fw ${firmware}` : ''}
            </p>
          )}

          {/* Actions */}
          <div className="flex flex-wrap items-center gap-3 pt-1">
            {/* Primary CTA — opens pre-filled GitHub issue */}
            <a
              href={reportUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold',
                'transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1',
                variant.buttonCls,
              )}
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              Report Results
            </a>

            {/* Secondary — dismiss link, visually subdued */}
            <button
              type="button"
              onClick={handleDismiss}
              className={cn(
                'text-xs underline underline-offset-2 transition-opacity hover:opacity-70',
                variant.bodyCls,
                'focus:outline-none',
              )}
            >
              Maybe Later
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
