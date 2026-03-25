/**
 * CamerasConfigForm — dynamic camera list editor.
 *
 * Allows the user to add new cameras, toggle enabled state, edit stream names,
 * and remove cameras. Camera names must be valid Frigate camera names.
 */

import { useState } from 'react';
import { Plus, Trash2, Camera, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/utils/cn';
import { inputCls, Field } from '@/components/common/FormField';
import type { CameraConfig, ConfigValidationError } from '@/types/config';

export interface CamerasConfigFormProps {
  value: Record<string, CameraConfig>;
  onChange: (value: Record<string, CameraConfig>) => void;
  errors: ConfigValidationError[];
}

/**
 * Audio codec options presented in the per-camera override dropdown.
 * The first entry (empty string value) means "inherit the global default".
 */
const AUDIO_CODEC_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Auto (use global default)' },
  { value: 'pcm_mulaw', label: 'G.711 mu-law (pcm_mulaw) — Reolink' },
  { value: 'pcm_alaw', label: 'G.711 A-law (pcm_alaw) — Dahua' },
];

interface CameraCardProps {
  /** Frigate camera name (used as the dict key). */
  name: string;
  /** Current config values for this camera. */
  cam: CameraConfig;
  /** Validation errors scoped to this camera. */
  errors: ConfigValidationError[];
  /** Called when any field on this camera changes. */
  onUpdate: (patch: Partial<CameraConfig>) => void;
  /** Called when the remove button is clicked. */
  onRemove: () => void;
}

/**
 * Single camera configuration card — rendered for each entry in the cameras map.
 *
 * Manages its own `audioExpanded` toggle state so the audio override section
 * is collapsed by default (most users won't need it) and each card is
 * independently expandable without lifting state to the parent.
 */
function CameraCard({ name, cam, errors, onUpdate, onRemove }: CameraCardProps) {
  const [audioExpanded, setAudioExpanded] = useState(false);

  const streamError = errors.find(
    (e) => e.field === `cameras.${name}.go2rtc_stream`,
  )?.message;

  // Determine if any audio override is currently set so we can show a hint
  // on the collapsed toggle even before the user expands it.
  const hasAudioOverride = !!(cam.audio_codec || cam.sample_rate || cam.channels);

  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700/50 dark:bg-gray-800/30">
      {/* Camera header — name, enabled toggle, remove button */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Camera className="h-4 w-4 text-gray-400" />
          <span className="font-mono text-sm font-semibold text-gray-900 dark:text-gray-100">
            {name}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
            <input
              type="checkbox"
              checked={cam.enabled}
              onChange={(e) => onUpdate({ enabled: e.target.checked })}
              className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600"
            />
            Enabled
          </label>
          <button
            onClick={onRemove}
            aria-label={`Remove camera ${name}`}
            className="rounded-lg p-1 text-gray-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* go2rtc stream name */}
      <Field label="go2rtc Stream Name" error={streamError}>
        <input
          type="text"
          value={cam.go2rtc_stream}
          onChange={(e) => onUpdate({ go2rtc_stream: e.target.value })}
          placeholder={name}
          className={inputCls(!!streamError)}
        />
      </Field>

      {/* Scene context */}
      <Field label="Scene Context (optional)">
        <textarea
          value={cam.scene_context ?? ''}
          onChange={(e) => onUpdate({ scene_context: e.target.value })}
          placeholder="Describe what the camera sees, e.g. 'The front door is on the left. The driveway is in the center. The kitchen window is on the right.'"
          rows={2}
          className={cn(inputCls(false), 'resize-y min-h-[3rem]')}
        />
        <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
          Gives the AI spatial awareness so it can say &quot;person near the kitchen window&quot; instead of generic descriptions.
        </p>
      </Field>

      {/* Audio codec override — collapsed by default since most cameras
          inherit the global default and this section is rarely needed. */}
      <div className="mt-3 rounded-lg border border-gray-200 dark:border-gray-700/50">
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
                value={cam.audio_codec ?? ''}
                onChange={(e) =>
                  onUpdate({ audio_codec: e.target.value || undefined })
                }
                className={inputCls(false)}
              >
                {AUDIO_CODEC_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </Field>

            {/* Sample rate + channels — only shown when a codec is selected
                so the user doesn't set orphaned values that have no effect. */}
            {cam.audio_codec && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Sample Rate (Hz)">
                  <input
                    type="number"
                    value={cam.sample_rate ?? 8000}
                    onChange={(e) =>
                      onUpdate({ sample_rate: Number(e.target.value) || undefined })
                    }
                    min={8000}
                    max={48000}
                    step={8000}
                    className={inputCls(false)}
                  />
                </Field>
                <Field label="Channels">
                  <select
                    value={cam.channels ?? 1}
                    onChange={(e) =>
                      onUpdate({ channels: Number(e.target.value) || undefined })
                    }
                    className={inputCls(false)}
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
    </div>
  );
}

/**
 * Dynamic camera configuration list (add, edit, remove, toggle).
 */
export function CamerasConfigForm({
  value,
  onChange,
  errors,
}: CamerasConfigFormProps) {
  const [newName, setNewName] = useState('');
  const [newNameError, setNewNameError] = useState('');

  const cameraNames = Object.keys(value);

  const addCamera = () => {
    const trimmed = newName.trim().toLowerCase().replace(/\s+/g, '_');
    if (!trimmed) {
      setNewNameError('Camera name is required.');
      return;
    }
    if (!/^[a-z0-9_-]+$/.test(trimmed)) {
      setNewNameError(
        'Camera name may only contain lowercase letters, numbers, hyphens, and underscores.',
      );
      return;
    }
    if (value[trimmed]) {
      setNewNameError(`Camera "${trimmed}" already exists.`);
      return;
    }
    onChange({
      ...value,
      [trimmed]: { enabled: true, go2rtc_stream: trimmed },
    });
    setNewName('');
    setNewNameError('');
  };

  const removeCamera = (name: string) => {
    const updated = { ...value };
    // eslint-disable-next-line @typescript-eslint/no-dynamic-delete
    delete updated[name];
    onChange(updated);
  };

  const updateCamera = (
    name: string,
    patch: Partial<CameraConfig>,
  ) => {
    const cam = value[name];
    if (!cam) return;
    onChange({ ...value, [name]: { ...cam, ...patch } });
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Camera names must exactly match Frigate camera names.
      </p>

      {errors.find((e) => e.field === 'cameras') && (
        <p className="text-sm text-red-500">
          {errors.find((e) => e.field === 'cameras')?.message}
        </p>
      )}

      {/* Existing cameras */}
      <div className="space-y-3">
        {cameraNames.length === 0 && (
          <div className="rounded-lg border border-dashed border-gray-300 py-8 text-center dark:border-gray-600">
            <Camera className="mx-auto mb-2 h-8 w-8 text-gray-300 dark:text-gray-600" />
            <p className="text-sm text-gray-500 dark:text-gray-400">
              No cameras configured yet.
            </p>
          </div>
        )}
        {cameraNames.map((name) => {
          const cam = value[name];
          if (!cam) return null;
          return (
            <CameraCard
              key={name}
              name={name}
              cam={cam}
              errors={errors}
              onUpdate={(patch) => updateCamera(name, patch)}
              onRemove={() => removeCamera(name)}
            />
          );
        })}
      </div>

      {/* Add new camera */}
      <div className="flex gap-2">
        <div className="flex-1">
          <input
            type="text"
            value={newName}
            onChange={(e) => {
              setNewName(e.target.value);
              setNewNameError('');
            }}
            onKeyDown={(e) => e.key === 'Enter' && addCamera()}
            placeholder="Camera name (e.g. frontdoor)"
            className={cn(
              inputCls(!!newNameError),
              'font-mono',
            )}
          />
          {newNameError && (
            <p className="mt-1 text-xs text-red-500">{newNameError}</p>
          )}
        </div>
        <button
          onClick={addCamera}
          className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <Plus className="h-4 w-4" />
          Add
        </button>
      </div>
    </div>
  );
}
