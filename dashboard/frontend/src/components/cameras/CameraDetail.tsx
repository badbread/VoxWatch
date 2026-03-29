/**
 * CameraDetail — per-camera expanded view with inline VoxWatch configuration.
 *
 * Sections:
 *  1. Camera Identification — ONVIF probe with model/manufacturer/firmware
 *  2. Two-Way Audio Support — backchannel detection with manual override
 *  3. VoxWatch Configuration — inline add / edit / remove (replaces the old
 *     redirect to Configuration > Cameras tab)
 *  4. Live Snapshot — auto-refreshing Frigate frame
 *  5. Frigate Stats — FPS and online status
 *
 * VoxWatch config panel behaviour:
 *  - If camera is NOT in config: "Add to VoxWatch" flow (requires backchannel
 *    or explicit override).
 *  - If camera IS in config: inline edit form with save, plus a
 *    "Remove from VoxWatch" button with confirmation guard.
 */

import { useEffect, useState } from 'react';
import {
  ArrowLeft,
  Volume2,
  Shield,
  Mic,
  AlertTriangle,
  Plus,
  Loader,
  CheckCircle,
  Search,
  Cpu,
  VolumeX,
  Speaker,
  Save,
  Trash2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { CameraSnapshotLive } from './CameraSnapshotLive';
import { CameraReportPrompt } from '@/components/common/CameraReportPrompt';
import { inputCls, Field } from '@/components/common/FormField';
import { getConfig, saveConfig } from '@/api/config';
import { identifyCamera } from '@/api/cameras';
import { useServiceStatus } from '@/hooks/useServiceStatus';
import { useStore } from '@/store';
import type { CameraStatus, CameraIdentifyResult, SpeakerStatus } from '@/types/status';
import type { CameraConfig } from '@/types/config';
import type { BadgeVariant } from '@/components/common/Badge';

export interface CameraDetailProps {
  camera: CameraStatus;
  onBack: () => void;
}

/**
 * Audio codec options for the per-camera override dropdown.
 * Empty string means "inherit the global default".
 */
const AUDIO_CODEC_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Auto (use global default)' },
  { value: 'pcm_mulaw', label: 'G.711 mu-law (pcm_mulaw) — Reolink' },
  { value: 'pcm_alaw', label: 'G.711 A-law (pcm_alaw) — Dahua' },
];

function cameraVariant(camera: CameraStatus): { variant: BadgeVariant; label: string } {
  if (camera.enabled && camera.frigate_online !== false) return { variant: 'connected', label: 'VoxWatch Enabled' };
  if (camera.enabled) return { variant: 'connected', label: 'VoxWatch Enabled' };
  if (camera.frigate_online === true) return { variant: 'neutral', label: 'Online' };
  if (camera.frigate_online === false) return { variant: 'error', label: 'Offline' };
  return { variant: 'neutral', label: 'Not Configured' };
}

/**
 * Determine whether the camera can support VoxWatch audio deterrent based on
 * the speaker_status resolved from the compatibility database.
 *
 * Returns a structured object so all downstream JSX can branch off it once.
 */
function resolveSpeakerCapability(
  identifyResult: CameraIdentifyResult | null,
  overrideBackchannel: boolean,
): {
  canAddToVoxWatch: boolean;
  requiresExternalSpeakerAck: boolean;
  speakerStatus: SpeakerStatus | null;
} {
  if (!identifyResult) {
    // Not yet identified — don't block anything
    return { canAddToVoxWatch: true, requiresExternalSpeakerAck: false, speakerStatus: null };
  }

  const s = identifyResult.speaker_status;

  if (s === 'none') {
    return { canAddToVoxWatch: false, requiresExternalSpeakerAck: false, speakerStatus: s };
  }
  if (s === 'rca_out') {
    return {
      canAddToVoxWatch: overrideBackchannel,
      requiresExternalSpeakerAck: true,
      speakerStatus: s,
    };
  }
  // built_in, unknown, override — allow
  return { canAddToVoxWatch: true, requiresExternalSpeakerAck: false, speakerStatus: s };
}

export function CameraDetail({ camera, onBack }: CameraDetailProps) {
  const { variant, label } = cameraVariant(camera);
  const [overrideBackchannel, setOverrideBackchannel] = useState(false);
  const [externalSpeakerAck, setExternalSpeakerAck] = useState(false);
  const [identifyResult, setIdentifyResult] = useState<CameraIdentifyResult | null>(null);
  const queryClient = useQueryClient();
  const addToast = useStore((s) => s.addToast);

  // Read Frigate and go2rtc versions from the status API so the community
  // report URL can include them without an extra API call.
  const { status } = useServiceStatus();


  // Mutation: identify camera model via ONVIF
  const identifyMutation = useMutation({
    mutationFn: () => identifyCamera(camera.name),
    onSuccess: (data) => {
      setIdentifyResult(data);
      // Reset external-speaker checkbox when a new identification arrives
      setExternalSpeakerAck(false);
    },
  });

  // Auto-identify camera when user selects a different camera.
  // Clears stale identification data immediately, then fires an ONVIF probe
  // so the user sees correct model/speaker info without clicking "Identify".
  useEffect(() => {
    setIdentifyResult(null);
    setOverrideBackchannel(false);
    setExternalSpeakerAck(false);
    identifyMutation.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera.name]);

  // Mutation: add this camera to VoxWatch config (for unconfigured cameras)
  const addCameraMutation = useMutation({
    mutationFn: async () => {
      const currentConfig = await getConfig();
      const cameras = currentConfig.cameras ?? {};
      // Add camera with defaults — uses Frigate stream name matching the camera name
      cameras[camera.name] = {
        enabled: true,
        go2rtc_stream: camera.name,
      };
      return saveConfig({ ...currentConfig, cameras });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      queryClient.invalidateQueries({ queryKey: ['status'] });
      queryClient.invalidateQueries({ queryKey: ['cameras', 'list'] });
      addToast(`${camera.name} added to VoxWatch.`, 'success');
    },
    onError: () => {
      addToast('Failed to add camera. Check backend logs.', 'error');
    },
  });

  const hasBackchannel = camera.has_backchannel === true || overrideBackchannel;

  // Resolve speaker capability from identification result
  const effectiveAck = externalSpeakerAck || overrideBackchannel;
  const { canAddToVoxWatch, requiresExternalSpeakerAck, speakerStatus } =
    resolveSpeakerCapability(identifyResult, effectiveAck);

  return (
    <div className="space-y-4">
      {/* Back button */}
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
      >
        <ArrowLeft className="h-4 w-4" />
        All cameras
      </button>

      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
          {camera.name}
        </h2>
        <Badge variant={variant} label={label} dot className="capitalize" />
      </div>

      {/* Camera Identification */}
      <Card title="Camera Identification">
        <div className="space-y-3">
          {/* Trigger button */}
          <button
            onClick={() => identifyMutation.mutate()}
            disabled={identifyMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-200 disabled:opacity-50 transition-colors dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            {identifyMutation.isPending ? (
              <Loader className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Search className="h-3.5 w-3.5" />
            )}
            {identifyMutation.isPending ? 'Identifying...' : 'Identify Camera'}
          </button>

          {/* Error state */}
          {identifyMutation.isError && (
            <p className="text-xs text-red-600 dark:text-red-400">
              Identification request failed. Check backend logs.
            </p>
          )}

          {/* Results */}
          {identifyResult && (
            <IdentifyResultPanel
              result={identifyResult}
              externalSpeakerAck={externalSpeakerAck}
              onExternalSpeakerAck={setExternalSpeakerAck}
              camera={camera}
              frigateVersion={status?.frigate.version}
              go2rtcVersion={status?.go2rtc.version}
            />
          )}
        </div>
      </Card>

      {/* Two-Way Audio Support */}
      <Card title="Two-Way Audio Support">
        {hasBackchannel ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <Mic className="h-4 w-4 text-green-500" />
              <span className="font-medium text-green-700 dark:text-green-400">
                {overrideBackchannel ? 'Two-way audio enabled (manual override)' : 'Two-way audio confirmed'}
              </span>
            </div>
            {camera.backchannel_codecs && camera.backchannel_codecs.length > 0 && (
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Supported codecs:{' '}
                <span className="font-mono text-gray-700 dark:text-gray-300">
                  {camera.backchannel_codecs.slice(0, 5).join(', ')}
                  {camera.backchannel_codecs.length > 5 && ` +${camera.backchannel_codecs.length - 5} more`}
                </span>
              </p>
            )}
          </div>
        ) : camera.has_backchannel === false ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm">
              <AlertTriangle className="h-4 w-4 text-yellow-500" />
              <span className="font-medium text-yellow-600 dark:text-yellow-400">
                Two-way audio not detected on current stream
              </span>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              go2rtc did not find an RTSP backchannel track on this camera&apos;s
              configured stream. This does not necessarily mean the camera lacks
              a speaker — some cameras (like Dahua/ONVIF models) expose the
              backchannel on a different stream profile than the one Frigate uses.
            </p>
            <button
              onClick={() => setOverrideBackchannel(true)}
              className="flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 transition-colors"
            >
              <Mic className="h-3.5 w-3.5" />
              This camera has a speaker — enable two-way audio
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm">
              <Mic className="h-4 w-4 text-gray-400" />
              <span className="font-medium text-gray-500 dark:text-gray-400">
                Two-way audio status unknown
              </span>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Could not query go2rtc for backchannel support. The camera may still support two-way audio.
            </p>
            <button
              onClick={() => setOverrideBackchannel(true)}
              className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 transition-colors"
            >
              Enable two-way audio manually
            </button>
          </div>
        )}
      </Card>

      {/* VoxWatch Configuration — inline add/edit/remove */}
      <Card title="VoxWatch Audio Deterrent">
        {camera.enabled ? (
          <VoxWatchEditPanel camera={camera} />
        ) : hasBackchannel ? (
          <VoxWatchAddPanel
            canAddToVoxWatch={canAddToVoxWatch}
            requiresExternalSpeakerAck={requiresExternalSpeakerAck}
            externalSpeakerAck={externalSpeakerAck}
            speakerStatus={speakerStatus}
            addCameraMutation={addCameraMutation}
          />
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm">
              <Shield className="h-4 w-4 text-gray-400" />
              <span className="font-medium text-gray-500 dark:text-gray-400">
                VoxWatch is not configured for this camera
              </span>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Enable two-way audio above first, then add this camera to VoxWatch.
            </p>
          </div>
        )}
      </Card>

      {/* Live snapshot */}
      <Card title="Live Snapshot" noPadding>
        <CameraSnapshotLive cameraName={camera.name} />
      </Card>

      {/* Frigate stats */}
      {camera.fps != null && (
        <Card title="Frigate Stats">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-gray-500 dark:text-gray-400">Detection FPS</span>
              <p className="font-mono font-semibold text-gray-900 dark:text-gray-100">
                {camera.fps.toFixed(1)}
              </p>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">Frigate Status</span>
              <p className="font-semibold text-green-600 dark:text-green-400">
                {camera.frigate_online ? 'Connected' : 'Disconnected'}
              </p>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// VoxWatch config panels — inline add and edit experiences
// ---------------------------------------------------------------------------

interface VoxWatchEditPanelProps {
  /** The currently configured camera. */
  camera: CameraStatus;
}

/**
 * Inline editor for a camera that is already in VoxWatch config.
 *
 * Lets the user:
 *  - Toggle enabled/disabled
 *  - Edit the go2rtc stream name
 *  - Edit the scene context
 *  - Override audio codec / sample rate / channels
 *  - Remove the camera from VoxWatch (with confirmation)
 *  - Test audio (link to /tests)
 */
function VoxWatchEditPanel({ camera }: VoxWatchEditPanelProps) {
  const queryClient = useQueryClient();
  const addToast = useStore((s) => s.addToast);
  const { status: svcStatus } = useServiceStatus();
  const otherCameraNames: string[] = (svcStatus?.cameras ?? [])
    .map((c) => c.name)
    .filter((n) => n !== camera.name);

  // Local draft state seeded from the current saved config.
  // We fetch the config once so we can read the full CameraConfig struct
  // (which has more fields than CameraStatus exposes).
  const [draft, setDraft] = useState<CameraConfig>({
    enabled: camera.enabled,
    go2rtc_stream: camera.name, // sensible default until config loads
    scene_context: '',
    audio_codec: undefined,
    sample_rate: undefined,
    channels: undefined,
  });
  const [loaded, setLoaded] = useState(false);
  const [audioExpanded, setAudioExpanded] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);

  // Load the full camera config when the panel first mounts
  const loadMutation = useMutation({
    mutationFn: async () => {
      const cfg = await getConfig();
      return cfg.cameras?.[camera.name] ?? null;
    },
    onSuccess: (camCfg) => {
      if (camCfg) {
        setDraft(camCfg);
      }
      setLoaded(true);
    },
  });

  // Trigger load on first render
  if (!loaded && !loadMutation.isPending && !loadMutation.isError) {
    loadMutation.mutate();
  }

  // Mutation: save the edited config
  const saveMutation = useMutation({
    mutationFn: async () => {
      const currentConfig = await getConfig();
      return saveConfig({
        ...currentConfig,
        cameras: {
          ...currentConfig.cameras,
          [camera.name]: draft,
        },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      queryClient.invalidateQueries({ queryKey: ['status'] });
      queryClient.invalidateQueries({ queryKey: ['cameras', 'list'] });
      addToast(`${camera.name} configuration saved.`, 'success');
    },
    onError: () => {
      addToast('Failed to save configuration. Check backend logs.', 'error');
    },
  });

  // Mutation: remove this camera from VoxWatch config
  const removeMutation = useMutation({
    mutationFn: async () => {
      const currentConfig = await getConfig();
      const cameras = { ...currentConfig.cameras };
      // eslint-disable-next-line @typescript-eslint/no-dynamic-delete
      delete cameras[camera.name];
      return saveConfig({ ...currentConfig, cameras });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      queryClient.invalidateQueries({ queryKey: ['status'] });
      queryClient.invalidateQueries({ queryKey: ['cameras', 'list'] });
      addToast(`${camera.name} removed from VoxWatch.`, 'success');
      setConfirmRemove(false);
    },
    onError: () => {
      addToast('Failed to remove camera. Check backend logs.', 'error');
    },
  });

  const hasAudioOverride = !!(draft.audio_codec || draft.sample_rate || draft.channels);
  const isBusy = saveMutation.isPending || removeMutation.isPending || loadMutation.isPending;

  return (
    <div className="space-y-4">
      {/* Status indicator */}
      <div className="flex items-center gap-2 text-sm">
        <Shield className="h-4 w-4 text-green-500" />
        <span className="font-medium text-green-700 dark:text-green-400">
          VoxWatch is enabled for this camera
        </span>
      </div>

      {/* Enable / disable toggle */}
      <label className="flex cursor-pointer items-center gap-3">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(e) => setDraft((prev) => ({ ...prev, enabled: e.target.checked }))}
          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600"
        />
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
          Enable VoxWatch audio deterrent
        </span>
      </label>

      {/* go2rtc stream name */}
      <Field label="go2rtc Stream Name">
        <input
          type="text"
          value={draft.go2rtc_stream}
          onChange={(e) => setDraft((prev) => ({ ...prev, go2rtc_stream: e.target.value }))}
          placeholder={camera.name}
          className={inputCls(false)}
          disabled={isBusy}
        />
      </Field>

      {/* Audio output speaker override */}
      <Field label="Audio Output Speaker">
        <select
          value={draft.audio_output ?? ''}
          onChange={(e) => setDraft((prev) => ({ ...prev, audio_output: e.target.value || '' }))}
          className={inputCls(false)}
          disabled={isBusy}
        >
          <option value="">Same camera (default)</option>
          {otherCameraNames.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
        </select>
        <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
          Which camera speaker plays audio when this camera detects someone.
        </p>
      </Field>

      {/* Scene context */}
      <Field label="Scene Context (optional)">
        <textarea
          value={draft.scene_context ?? ''}
          onChange={(e) => setDraft((prev) => ({ ...prev, scene_context: e.target.value || '' }))}
          placeholder="Describe what the camera sees, e.g. 'The front door is on the left. The driveway is in the center.'"
          rows={2}
          className={cn(inputCls(false), 'resize-y min-h-[3rem]')}
          disabled={isBusy}
        />
        <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
          Gives the AI spatial awareness so it can say &quot;person near the kitchen window&quot; instead of generic descriptions.
        </p>
      </Field>

      {/* Audio codec override — collapsed by default */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700/50">
        <button
          type="button"
          onClick={() => setAudioExpanded((prev) => !prev)}
          className={cn(
            'flex w-full items-center justify-between px-3 py-2 text-xs font-medium transition-colors',
            'text-gray-500 hover:bg-gray-100/60 dark:text-gray-400 dark:hover:bg-gray-700/30',
            audioExpanded && 'border-b border-gray-200 dark:border-gray-700/50',
          )}
        >
          <span className="flex items-center gap-1.5">
            Audio Codec Override
            {hasAudioOverride && (
              <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                custom
              </span>
            )}
          </span>
          {audioExpanded ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </button>

        {audioExpanded && (
          <div className="space-y-3 px-3 py-3">
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Override the global audio settings for this camera. Only needed when cameras on your network use different codecs (e.g. Reolink uses mu-law, Dahua uses A-law).
            </p>

            {/* Codec dropdown */}
            <Field label="Audio Codec">
              <select
                value={draft.audio_codec ?? ''}
                onChange={(e) =>
                  setDraft((prev) => ({ ...prev, audio_codec: e.target.value || undefined }))
                }
                className={inputCls(false)}
                disabled={isBusy}
              >
                {AUDIO_CODEC_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </Field>

            {/* Sample rate + channels — only shown when a codec is selected */}
            {draft.audio_codec && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Sample Rate (Hz)">
                  <input
                    type="number"
                    value={draft.sample_rate ?? 8000}
                    onChange={(e) =>
                      setDraft((prev) => ({ ...prev, sample_rate: Number(e.target.value) || undefined }))
                    }
                    min={8000}
                    max={48000}
                    step={8000}
                    className={inputCls(false)}
                    disabled={isBusy}
                  />
                </Field>
                <Field label="Channels">
                  <select
                    value={draft.channels ?? 1}
                    onChange={(e) =>
                      setDraft((prev) => ({ ...prev, channels: Number(e.target.value) || undefined }))
                    }
                    className={inputCls(false)}
                    disabled={isBusy}
                  >
                    <option value={1}>1 (Mono)</option>
                    <option value={2}>2 (Stereo)</option>
                  </select>
                </Field>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Action row — Save + Test Audio + Remove */}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={isBusy}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
        >
          {saveMutation.isPending ? (
            <Loader className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          {saveMutation.isPending ? 'Saving...' : 'Save Changes'}
        </button>

        <Link
          to="/tests"
          className="inline-flex items-center gap-1.5 rounded-lg border border-blue-300 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 dark:border-blue-700 dark:bg-blue-950/30 dark:text-blue-300 dark:hover:bg-blue-950/50 transition-colors"
        >
          <Volume2 className="h-3.5 w-3.5" />
          Test Audio
        </Link>

        {/* Remove button — two-step confirmation to prevent accidental removal */}
        {!confirmRemove ? (
          <button
            onClick={() => setConfirmRemove(true)}
            disabled={isBusy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-100 disabled:opacity-50 dark:border-red-800/50 dark:bg-red-950/20 dark:text-red-400 dark:hover:bg-red-950/40 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Remove from VoxWatch
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 dark:text-gray-400">Are you sure?</span>
            <button
              onClick={() => removeMutation.mutate()}
              disabled={isBusy}
              className="inline-flex items-center gap-1 rounded-lg bg-red-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
            >
              {removeMutation.isPending ? <Loader className="h-3 w-3 animate-spin" /> : 'Confirm'}
            </button>
            <button
              onClick={() => setConfirmRemove(false)}
              className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {saveMutation.isError && (
        <p className="text-xs text-red-600 dark:text-red-400">
          Failed to save. Check backend logs.
        </p>
      )}
      {removeMutation.isError && (
        <p className="text-xs text-red-600 dark:text-red-400">
          Failed to remove. Check backend logs.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

/** Minimal mutation state shape consumed by VoxWatchAddPanel. */
interface AddCameraMutationState {
  isPending: boolean;
  isSuccess: boolean;
  isError: boolean;
  mutate: () => void;
}

interface VoxWatchAddPanelProps {
  canAddToVoxWatch: boolean;
  requiresExternalSpeakerAck: boolean;
  externalSpeakerAck: boolean;
  speakerStatus: SpeakerStatus | null;
  addCameraMutation: AddCameraMutationState;
}

/**
 * The "Add to VoxWatch" panel shown when the camera supports backchannel but
 * has not yet been added to VoxWatch config.
 *
 * Disables the add button when the camera has no audio output, and shows a
 * prompt to acknowledge an external speaker for RCA-out cameras.
 *
 * After adding, the camera config can be edited inline via VoxWatchEditPanel —
 * which will appear once the cameras list refreshes.
 */
function VoxWatchAddPanel({
  canAddToVoxWatch,
  requiresExternalSpeakerAck,
  externalSpeakerAck,
  speakerStatus,
  addCameraMutation,
}: VoxWatchAddPanelProps) {
  const isIncompatible = speakerStatus === 'none';
  const isBlockedByAck = requiresExternalSpeakerAck && !externalSpeakerAck;

  return (
    <div className={`space-y-3 ${isIncompatible ? 'opacity-60' : ''}`}>
      <div className="flex items-center gap-2 text-sm">
        <Shield className={`h-4 w-4 ${isIncompatible ? 'text-red-400' : 'text-gray-400'}`} />
        <span className={`font-medium ${isIncompatible ? 'text-red-500 dark:text-red-400' : 'text-gray-500 dark:text-gray-400'}`}>
          {isIncompatible
            ? 'VoxWatch cannot be enabled — no audio output'
            : 'VoxWatch is not configured for this camera'}
        </span>
      </div>

      {!isIncompatible && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          {isBlockedByAck
            ? 'Confirm you have connected an external speaker above, then add this camera.'
            : 'This camera supports two-way audio. Add it to VoxWatch to enable AI-powered audio deterrent.'}
        </p>
      )}

      <button
        onClick={() => addCameraMutation.mutate()}
        disabled={!canAddToVoxWatch || addCameraMutation.isPending}
        className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-40 transition-colors"
      >
        {addCameraMutation.isPending ? (
          <Loader className="h-3.5 w-3.5 animate-spin" />
        ) : addCameraMutation.isSuccess ? (
          <CheckCircle className="h-3.5 w-3.5" />
        ) : (
          <Plus className="h-3.5 w-3.5" />
        )}
        {addCameraMutation.isPending
          ? 'Adding...'
          : addCameraMutation.isSuccess
            ? 'Added to VoxWatch'
            : 'Add to VoxWatch'}
      </button>

      {addCameraMutation.isError && (
        <p className="text-xs text-red-600 dark:text-red-400">
          Failed to add camera. Check backend logs.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Identification sub-components (unchanged from original)
// ---------------------------------------------------------------------------

interface IdentifyResultPanelProps {
  result: CameraIdentifyResult;
  externalSpeakerAck: boolean;
  onExternalSpeakerAck: (v: boolean) => void;
  /** Full camera status — passed through to CompatibilityBanner for report data. */
  camera: CameraStatus;
  /** Frigate version from status API. */
  frigateVersion?: string | undefined;
  /** go2rtc version from status API. */
  go2rtcVersion?: string | undefined;
}

/**
 * Renders the ONVIF identification result and the compatibility banner
 * appropriate for the resolved speaker_status.
 */
function IdentifyResultPanel({
  result,
  externalSpeakerAck,
  onExternalSpeakerAck,
  camera,
  frigateVersion,
  go2rtcVersion,
}: IdentifyResultPanelProps) {
  if (!result.identified) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/50">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-gray-400" />
          <div className="space-y-1">
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Could not identify camera
            </p>
            {result.error && (
              <p className="text-xs text-gray-500 dark:text-gray-400">{result.error}</p>
            )}
            {result.camera_ip && (
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Probed IP:{' '}
                <span className="font-mono text-gray-700 dark:text-gray-300">
                  {result.camera_ip}
                </span>
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Device info table */}
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/50">
        <div className="flex items-start gap-2">
          <Cpu className="mt-0.5 h-4 w-4 flex-shrink-0 text-gray-400" />
          <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
            {result.manufacturer && (
              <>
                <span className="text-gray-500 dark:text-gray-400">Manufacturer</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {result.manufacturer}
                </span>
              </>
            )}
            {result.model && (
              <>
                <span className="text-gray-500 dark:text-gray-400">Model</span>
                <span className="font-mono font-medium text-gray-900 dark:text-gray-100">
                  {result.model}
                </span>
              </>
            )}
            {result.firmware && (
              <>
                <span className="text-gray-500 dark:text-gray-400">Firmware</span>
                <span className="font-mono text-gray-700 dark:text-gray-300">
                  {result.firmware}
                </span>
              </>
            )}
            {result.camera_ip && (
              <>
                <span className="text-gray-500 dark:text-gray-400">IP Address</span>
                <span className="font-mono text-gray-700 dark:text-gray-300">
                  {result.camera_ip}
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Compatibility banner */}
      <CompatibilityBanner
        speakerStatus={result.speaker_status}
        notes={result.compatibility?.notes ?? null}
        externalSpeakerAck={externalSpeakerAck}
        onExternalSpeakerAck={onExternalSpeakerAck}
        inDatabase={result.compatibility !== null}
        identifyResult={result}
        camera={camera}
        frigateVersion={frigateVersion}
        go2rtcVersion={go2rtcVersion}
      />
    </div>
  );
}

interface CompatibilityBannerProps {
  speakerStatus: SpeakerStatus;
  notes: string | null;
  externalSpeakerAck: boolean;
  onExternalSpeakerAck: (v: boolean) => void;
  inDatabase: boolean;
  /** ONVIF identification result — used to populate the community report prompt. */
  identifyResult: CameraIdentifyResult;
  /** CameraStatus for the current camera — provides backchannel codecs. */
  camera: CameraStatus;
  /** Frigate version from status API — forwarded to the report URL builder. */
  frigateVersion?: string | undefined;
  /** go2rtc version from status API — forwarded to the report URL builder. */
  go2rtcVersion?: string | undefined;
}

/**
 * Shows the appropriate coloured compatibility notice based on speaker_status.
 * Each status maps to a distinct colour and guidance message.
 *
 * When the camera is not in the database (speaker_status === 'unknown') the
 * banner is replaced by the full CameraReportPrompt component so the user
 * gets a clear, prominent invitation to contribute their findings.
 */
function CompatibilityBanner({
  speakerStatus,
  notes,
  externalSpeakerAck,
  onExternalSpeakerAck,
  inDatabase: _inDatabase,
  identifyResult,
  camera,
  frigateVersion,
  go2rtcVersion,
}: CompatibilityBannerProps) {
  if (speakerStatus === 'none') {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-800/60 dark:bg-red-900/20">
        <div className="flex items-start gap-2">
          <VolumeX className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-500" />
          <div className="space-y-1">
            <p className="text-sm font-semibold text-red-700 dark:text-red-400">
              This camera has no audio output. VoxWatch audio deterrent will not work.
            </p>
            {notes && (
              <p className="text-xs text-red-600 dark:text-red-400">{notes}</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (speakerStatus === 'rca_out') {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-800/60 dark:bg-amber-900/20">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-500" />
          <div className="space-y-2 w-full">
            <p className="text-sm font-semibold text-amber-700 dark:text-amber-400">
              This camera has RCA audio output but no built-in speaker. Connect an
              external speaker to use VoxWatch.
            </p>
            {notes && (
              <p className="text-xs text-amber-600 dark:text-amber-400">{notes}</p>
            )}
            <label className="flex cursor-pointer items-center gap-2 text-sm text-amber-700 dark:text-amber-300">
              <input
                type="checkbox"
                checked={externalSpeakerAck}
                onChange={(e) => onExternalSpeakerAck(e.target.checked)}
                className="h-4 w-4 rounded border-amber-400 text-amber-600 focus:ring-amber-500"
              />
              I have connected an external speaker
            </label>
          </div>
        </div>
      </div>
    );
  }

  if (speakerStatus === 'built_in') {
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-800/60 dark:bg-green-900/20">
        <div className="flex items-start gap-2">
          <CheckCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-green-500" />
          <div className="space-y-1">
            <p className="text-sm font-semibold text-green-700 dark:text-green-400">
              Built-in speaker detected. Compatible with VoxWatch.
            </p>
            {notes && (
              <p className="text-xs text-green-600 dark:text-green-400">{notes}</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  // unknown — model not in database: show the full report prompt
  return (
    <div className="space-y-3">
      {/* Brief orientation note before the report prompt */}
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-800/60 dark:bg-blue-900/20">
        <div className="flex items-start gap-2">
          <Speaker className="mt-0.5 h-4 w-4 flex-shrink-0 text-blue-500" />
          <div className="space-y-1">
            <p className="text-sm font-semibold text-blue-700 dark:text-blue-400">
              Camera model not in our database. Audio may or may not work.
            </p>
            <p className="text-xs text-blue-600 dark:text-blue-400">
              Run a test audio push to confirm compatibility, then report your
              results below so this camera can be added to the database.
            </p>
            <Link
              to="/tests"
              className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-200"
            >
              <Volume2 className="h-3 w-3" />
              Test Audio
            </Link>
          </div>
        </div>
      </div>

      {/* Community report prompt — prominent CTA for unknown cameras */}
      <CameraReportPrompt
        cameraName={camera.name}
        manufacturer={identifyResult.manufacturer ?? undefined}
        model={identifyResult.model ?? undefined}
        firmware={identifyResult.firmware ?? undefined}
        ip={identifyResult.camera_ip ?? undefined}
        backchannelCodecs={camera.backchannel_codecs}
        hasBackchannel={camera.has_backchannel}
        audioResult="failed"
        frigateVersion={frigateVersion}
        go2rtcVersion={go2rtcVersion}
      />
    </div>
  );
}
