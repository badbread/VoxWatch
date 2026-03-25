/**
 * CameraDetail — per-camera expanded view with backchannel detection,
 * camera model identification, VoxWatch setup, live snapshot, and Frigate stats.
 */

import { useState } from 'react';
import {
  ArrowLeft,
  Volume2,
  Shield,
  Settings,
  Mic,
  AlertTriangle,
  Plus,
  Loader,
  CheckCircle,
  Search,
  Cpu,
  ExternalLink,
  VolumeX,
  Speaker,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { CameraSnapshotLive } from './CameraSnapshotLive';
import { getConfig, saveConfig } from '@/api/config';
import { identifyCamera } from '@/api/cameras';
import type { CameraStatus, CameraIdentifyResult, SpeakerStatus } from '@/types/status';
import type { BadgeVariant } from '@/components/common/Badge';

export interface CameraDetailProps {
  camera: CameraStatus;
  onBack: () => void;
}

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
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Mutation: identify camera model via ONVIF
  const identifyMutation = useMutation({
    mutationFn: () => identifyCamera(camera.name),
    onSuccess: (data) => {
      setIdentifyResult(data);
      // Reset external-speaker checkbox when a new identification arrives
      setExternalSpeakerAck(false);
    },
  });

  // Mutation: add this camera to VoxWatch config
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
      // Invalidate queries so dashboard picks up the new camera
      queryClient.invalidateQueries({ queryKey: ['config'] });
      queryClient.invalidateQueries({ queryKey: ['status'] });
      // Navigate to config page with cameras tab
      setTimeout(() => navigate('/config?tab=cameras'), 500);
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
              go2rtc did not find an RTSP backchannel track on this camera's
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

      {/* VoxWatch Configuration */}
      <Card title="VoxWatch Audio Deterrent">
        {camera.enabled ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm">
              <Shield className="h-4 w-4 text-green-500" />
              <span className="font-medium text-green-700 dark:text-green-400">
                VoxWatch is enabled for this camera
              </span>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              AI-powered audio warnings will play when a person is detected.
            </p>
            <div className="flex gap-2 pt-1">
              <Link
                to="/config"
                className="flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 transition-colors"
              >
                <Settings className="h-3.5 w-3.5" />
                Edit Configuration
              </Link>
              <Link
                to="/audio"
                className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 transition-colors"
              >
                <Volume2 className="h-3.5 w-3.5" />
                Test Audio
              </Link>
            </div>
          </div>
        ) : hasBackchannel ? (
          <VoxWatchConfigPanel
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
// Sub-components
// ---------------------------------------------------------------------------

interface IdentifyResultPanelProps {
  result: CameraIdentifyResult;
  externalSpeakerAck: boolean;
  onExternalSpeakerAck: (v: boolean) => void;
}

/**
 * Renders the ONVIF identification result and the compatibility banner
 * appropriate for the resolved speaker_status.
 */
function IdentifyResultPanel({
  result,
  externalSpeakerAck,
  onExternalSpeakerAck,
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
}

/**
 * Shows the appropriate coloured compatibility notice based on speaker_status.
 * Each status maps to a distinct colour and guidance message.
 */
function CompatibilityBanner({
  speakerStatus,
  notes,
  externalSpeakerAck,
  onExternalSpeakerAck,
  inDatabase: _inDatabase,
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

  // unknown — model not in database
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-800/60 dark:bg-blue-900/20">
      <div className="flex items-start gap-2">
        <Speaker className="mt-0.5 h-4 w-4 flex-shrink-0 text-blue-500" />
        <div className="space-y-2">
          <p className="text-sm font-semibold text-blue-700 dark:text-blue-400">
            Camera model not in our database. Audio may or may not work.
          </p>
          <p className="text-xs text-blue-600 dark:text-blue-400">
            Run a test audio push to confirm compatibility, or report this camera
            so it can be added to the database.
          </p>
          <div className="flex items-center gap-3">
            <Link
              to="/audio"
              className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-200"
            >
              <Volume2 className="h-3 w-3" />
              Test Audio
            </Link>
            <a
              href="https://github.com/BadBread/voxwatch/issues/new?template=camera_compat.md"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-200"
            >
              <ExternalLink className="h-3 w-3" />
              Report this camera
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Minimal mutation state shape consumed by VoxWatchConfigPanel. */
interface AddCameraMutationState {
  isPending: boolean;
  isSuccess: boolean;
  isError: boolean;
  mutate: () => void;
}

interface VoxWatchConfigPanelProps {
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
 */
function VoxWatchConfigPanel({
  canAddToVoxWatch,
  requiresExternalSpeakerAck,
  externalSpeakerAck,
  speakerStatus,
  addCameraMutation,
}: VoxWatchConfigPanelProps) {
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
            ? 'Added — redirecting to config...'
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
