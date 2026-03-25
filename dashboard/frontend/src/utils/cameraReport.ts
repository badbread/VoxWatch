/**
 * cameraReport.ts — Utility for building pre-filled GitHub issue URLs for
 * camera compatibility reports.
 *
 * The GitHub issue form field `id` values in camera_report.yml map directly
 * to query parameters supported by GitHub's new-issue URL scheme. This
 * utility assembles those parameters from the data VoxWatch has already
 * collected during camera identification and audio testing.
 *
 * GitHub pre-fill reference:
 *   https://docs.github.com/en/issues/tracking-your-work-with-issues/creating-an-issue#creating-an-issue-from-a-url-query
 */

/** Repository where camera reports should be filed. */
const REPO_URL = 'https://github.com/badbread/VoxWatch';

/** Maps the audioResult prop value to the matching dropdown label in camera_report.yml. */
const AUDIO_RESULT_LABELS: Record<string, string> = {
  success: 'Yes — heard audio clearly',
  garbled: 'Yes — but audio was garbled/distorted',
  partial: 'Partially — intermittent/unreliable',
  failed: 'No — no audio at all',
};

/** Maps speaker type values to the matching dropdown label in camera_report.yml. */
const SPEAKER_TYPE_LABELS: Record<string, string> = {
  built_in: 'Built-in speaker (plays audio from the camera itself)',
  rca_out: 'RCA audio out only (needs external speaker connected)',
  none: 'No speaker or audio output at all',
  unknown: 'Not sure',
  override: 'Built-in speaker (plays audio from the camera itself)',
  'not sure': 'Not sure',
};

/**
 * Maps a list of raw backchannel codec strings to the best-matching dropdown
 * option in the camera_report.yml backchannel_codec field.
 *
 * @param codecs - Raw codec strings from go2rtc (e.g. ["PCMU/8000", "PCMA/8000"]).
 * @param hasBackchannel - Whether go2rtc detected a backchannel track at all.
 * @returns The matching dropdown label string.
 */
function resolveBackchannelCodecLabel(
  codecs: string[] | undefined,
  hasBackchannel: boolean | undefined,
): string {
  if (!hasBackchannel) return 'No backchannel detected';
  if (!codecs || codecs.length === 0) return 'Not sure';

  const upper = codecs.map((c) => c.toUpperCase());
  const hasPcmu = upper.some((c) => c.startsWith('PCMU'));
  const hasPcma = upper.some((c) => c.startsWith('PCMA'));

  if (codecs.length > 1) return 'Multiple codecs available';
  if (hasPcmu) return 'PCMU/8000 (G.711 mu-law)';
  if (hasPcma) return 'PCMA/8000 (G.711 A-law)';
  return 'Not sure';
}

/** Parameters accepted by buildCameraReportUrl. */
export interface CameraReportParams {
  /** Camera make string from ONVIF (e.g. "Reolink"). */
  manufacturer?: string | undefined;
  /** Full model string from ONVIF (e.g. "CX410"). */
  model?: string | undefined;
  /** Firmware version string from ONVIF. */
  firmware?: string | undefined;
  /** Camera IP address that was probed. */
  ip?: string | undefined;
  /** Raw backchannel codec strings from go2rtc (e.g. ["PCMU/8000"]). */
  backchannelCodecs?: string[] | undefined;
  /** Whether go2rtc detected a backchannel track. */
  hasBackchannel?: boolean | undefined;
  /** Self-reported audio test outcome. */
  audioResult?: 'success' | 'failed' | 'garbled' | 'partial' | undefined;
  /** Speaker type from the camera database or "not sure". */
  speakerType?: string | undefined;
  /** Frigate version string from the status API. */
  frigateVersion?: string | undefined;
  /** go2rtc version string from the status API. */
  go2rtcVersion?: string | undefined;
  /** VoxWatch dashboard version. */
  voxwatchVersion?: string | undefined;
  /** RTSP stream URL (with credentials replaced by user:pass). */
  rtspUrl?: string | undefined;
  /** Any extra notes the user or the UI wants to pre-fill. */
  notes?: string | undefined;
}

/**
 * Builds a GitHub new-issue URL with all known camera data pre-filled into
 * the camera_report.yml form fields.
 *
 * Field IDs used (must match camera_report.yml exactly):
 *   manufacturer, model, firmware, speaker_type, audio_works,
 *   backchannel_codec, go2rtc_stream_url, notes, auto_detected
 *
 * @param params - Camera and test data collected by the dashboard.
 * @returns A fully-formed URL string that opens the GitHub issue form.
 */
export function buildCameraReportUrl(params: CameraReportParams): string {
  const {
    manufacturer = '',
    model = '',
    firmware = '',
    ip = '',
    backchannelCodecs,
    hasBackchannel,
    audioResult,
    speakerType,
    frigateVersion,
    go2rtcVersion,
    voxwatchVersion,
    rtspUrl,
    notes,
  } = params;

  const mfr = manufacturer || 'Unknown';
  const mdl = model || 'Unknown';

  // Build the auto_detected YAML block that gets pre-filled into the textarea.
  // Only include fields we actually have data for to keep it readable.
  const autoDetectedLines: string[] = [
    `manufacturer: ${mfr}`,
    `model: ${mdl}`,
  ];

  if (firmware) autoDetectedLines.push(`firmware: ${firmware}`);
  if (ip) autoDetectedLines.push(`camera_ip: ${ip}`);
  if (hasBackchannel !== undefined) {
    autoDetectedLines.push(`has_backchannel: ${hasBackchannel}`);
  }
  if (backchannelCodecs && backchannelCodecs.length > 0) {
    autoDetectedLines.push(`backchannel_codecs: [${backchannelCodecs.join(', ')}]`);
  }
  if (audioResult) {
    autoDetectedLines.push(`audio_test_result: ${audioResult}`);
  }
  if (frigateVersion) autoDetectedLines.push(`frigate_version: ${frigateVersion}`);
  if (go2rtcVersion) autoDetectedLines.push(`go2rtc_version: ${go2rtcVersion}`);
  if (voxwatchVersion) autoDetectedLines.push(`voxwatch_version: ${voxwatchVersion}`);

  const autoDetected = autoDetectedLines.join('\n');

  // Map structured values to the dropdown labels used in camera_report.yml
  const audioWorksLabel = audioResult ? (AUDIO_RESULT_LABELS[audioResult] ?? 'Did not test') : 'Did not test';
  const speakerTypeLabel = speakerType
    ? (SPEAKER_TYPE_LABELS[speakerType] ?? 'Not sure')
    : 'Not sure';
  const backchannelCodecLabel = resolveBackchannelCodecLabel(backchannelCodecs, hasBackchannel);

  const searchParams = new URLSearchParams({
    template: 'camera_report.yml',
    title: `Camera Report: ${mfr} ${mdl}`,
    // Fields matching camera_report.yml id values:
    manufacturer: mfr,
    model: mdl,
    firmware: firmware || '',
    speaker_type: speakerTypeLabel,
    audio_works: audioWorksLabel,
    backchannel_codec: backchannelCodecLabel,
    auto_detected: autoDetected,
  });

  // Optional fields — only include when we have data to avoid cluttering the URL
  if (rtspUrl) searchParams.set('go2rtc_stream_url', rtspUrl);
  if (notes) searchParams.set('notes', notes);

  return `${REPO_URL}/issues/new?${searchParams.toString()}`;
}
