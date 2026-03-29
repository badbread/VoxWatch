/**
 * ConditionsConfigForm — detection trigger conditions settings.
 *
 * Covers: min_score slider, cooldown_seconds, active_hours mode with
 * conditional sub-fields for fixed/sunset_sunrise modes (city input,
 * advanced lat/lon collapsible, offset inputs), and per-camera schedule
 * overrides that update the cameras config directly.
 */

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { errorForField } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import { formatScore } from '@/utils/formatters';
import type {
  ConditionsConfig,
  CameraConfig,
  CameraSchedule,
  ConfigValidationError,
} from '@/types/config';

export interface ConditionsConfigFormProps {
  value: ConditionsConfig;
  cameras: Record<string, CameraConfig>;
  onChange: (value: ConditionsConfig) => void;
  onCamerasChange: (cameras: Record<string, CameraConfig>) => void;
  errors: ConfigValidationError[];
}

/**
 * Returns only the cameras that have VoxWatch enabled.
 */
function enabledCameras(
  cameras: Record<string, CameraConfig>,
): [string, CameraConfig][] {
  return Object.entries(cameras).filter(([, cfg]) => cfg.enabled);
}

/**
 * Compact label for a CameraSchedule mode used in the dropdown.
 */
const SCHEDULE_MODE_LABELS: Record<
  CameraSchedule['mode'] | 'global',
  string
> = {
  global: 'Use global',
  always: 'Always (24/7)',
  scheduled: 'Scheduled',
  sunset_sunrise: 'Sunset/Sunrise',
};

/**
 * Single per-camera schedule row — mode dropdown plus conditional inline inputs.
 */
function CameraScheduleRow({
  cameraName,
  cameraConfig,
  onChange,
}: {
  cameraName: string;
  cameraConfig: CameraConfig;
  onChange: (updated: CameraConfig) => void;
}) {
  const schedule = cameraConfig.schedule;
  const activeMode: CameraSchedule['mode'] | 'global' = schedule
    ? schedule.mode
    : 'global';

  /** Update the schedule sub-object, or remove it when reverting to global. */
  const handleModeChange = (
    raw: string,
  ) => {
    const next = raw as CameraSchedule['mode'] | 'global';
    if (next === 'global') {
      const { schedule: _removed, ...rest } = cameraConfig;
      onChange(rest as CameraConfig);
    } else {
      // Seed sensible defaults for the chosen mode.
      const base: CameraSchedule = { mode: next };
      if (next === 'scheduled') {
        base.start = schedule?.start ?? '22:00';
        base.end = schedule?.end ?? '06:00';
      }
      if (next === 'sunset_sunrise') {
        base.sunset_offset_minutes = schedule?.sunset_offset_minutes ?? 0;
        base.sunrise_offset_minutes = schedule?.sunrise_offset_minutes ?? 0;
      }
      onChange({ ...cameraConfig, schedule: base });
    }
  };

  const patchSchedule = (patch: Partial<CameraSchedule>) => {
    if (!schedule) return;
    onChange({ ...cameraConfig, schedule: { ...schedule, ...patch } });
  };

  return (
    <div className="flex flex-wrap items-center gap-2 py-2">
      {/* Camera name */}
      <span className="w-36 flex-shrink-0 truncate text-sm font-medium text-gray-800 dark:text-gray-200">
        {cameraName}
      </span>

      {/* Mode dropdown */}
      <select
        value={activeMode}
        onChange={(e) => handleModeChange(e.target.value)}
        className={`w-40 flex-shrink-0 ${inputCls(false)}`}
        aria-label={`Schedule mode for ${cameraName}`}
      >
        {(
          Object.entries(SCHEDULE_MODE_LABELS) as [
            CameraSchedule['mode'] | 'global',
            string,
          ][]
        ).map(([val, label]) => (
          <option key={val} value={val}>
            {label}
          </option>
        ))}
      </select>

      {/* Scheduled: start / end time inputs */}
      {activeMode === 'scheduled' && schedule && (
        <>
          <input
            type="time"
            value={schedule.start ?? '22:00'}
            onChange={(e) => patchSchedule({ start: e.target.value })}
            className={`w-32 ${inputCls(false)}`}
            aria-label={`Start time for ${cameraName}`}
          />
          <span className="text-xs text-gray-400">—</span>
          <input
            type="time"
            value={schedule.end ?? '06:00'}
            onChange={(e) => patchSchedule({ end: e.target.value })}
            className={`w-32 ${inputCls(false)}`}
            aria-label={`End time for ${cameraName}`}
          />
        </>
      )}

      {/* Sunset/Sunrise: offset inputs */}
      {activeMode === 'sunset_sunrise' && schedule && (
        <>
          <div className="flex items-center gap-1">
            <input
              type="number"
              value={schedule.sunset_offset_minutes ?? 0}
              onChange={(e) =>
                patchSchedule({ sunset_offset_minutes: Number(e.target.value) })
              }
              step={5}
              className={`w-20 ${inputCls(false)}`}
              aria-label={`Sunset offset minutes for ${cameraName}`}
            />
            <span className="text-xs text-gray-400 dark:text-gray-500">
              sunset
            </span>
          </div>
          <div className="flex items-center gap-1">
            <input
              type="number"
              value={schedule.sunrise_offset_minutes ?? 0}
              onChange={(e) =>
                patchSchedule({
                  sunrise_offset_minutes: Number(e.target.value),
                })
              }
              step={5}
              className={`w-20 ${inputCls(false)}`}
              aria-label={`Sunrise offset minutes for ${cameraName}`}
            />
            <span className="text-xs text-gray-400 dark:text-gray-500">
              sunrise
            </span>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Detection trigger conditions form.
 */
export function ConditionsConfigForm({
  value,
  cameras,
  onChange,
  onCamerasChange,
  errors,
}: ConditionsConfigFormProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const set = <K extends keyof ConditionsConfig>(
    k: K,
    v: ConditionsConfig[K],
  ) => onChange({ ...value, [k]: v });

  const setHours = <K extends keyof ConditionsConfig['active_hours']>(
    k: K,
    v: ConditionsConfig['active_hours'][K],
  ) =>
    onChange({
      ...value,
      active_hours: { ...value.active_hours, [k]: v },
    });

  const isSunsetMode = value.active_hours.mode === 'sunset_sunrise';

  const handleCameraChange = (name: string, updated: CameraConfig) => {
    onCamerasChange({ ...cameras, [name]: updated });
  };

  const activeCameras = enabledCameras(cameras);

  return (
    <div className="space-y-5">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        All conditions must be met for the deterrent to trigger.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* Min score */}
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
              Minimum Detection Score
            </label>
            <span className="font-mono text-xs font-semibold text-blue-600 dark:text-blue-400">
              {formatScore(value.min_score)}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={Math.round(value.min_score * 100)}
            onChange={(e) => set('min_score', Number(e.target.value) / 100)}
            className="w-full accent-blue-600"
          />
          <div className="mt-0.5 flex justify-between text-xs text-gray-400">
            <span>0%</span>
            <span>100%</span>
          </div>
          {errorForField(errors, 'conditions.min_score') && (
            <p className="mt-1 text-xs text-red-500">
              {errorForField(errors, 'conditions.min_score')}
            </p>
          )}
        </div>

        {/* Cooldown */}
        <Field
          label="Cooldown Seconds"
          error={errorForField(errors, 'conditions.cooldown_seconds')}
          hint="Per-camera minimum gap between triggers"
        >
          <input
            type="number"
            value={value.cooldown_seconds}
            onChange={(e) => set('cooldown_seconds', Number(e.target.value))}
            min={0}
            step={5}
            className={inputCls(
              !!errorForField(errors, 'conditions.cooldown_seconds'),
            )}
          />
        </Field>
      </div>

      {/* Active hours */}
      <div className="rounded-xl border border-gray-200 p-4 dark:border-gray-700/50">
        <Field
          label="Active Hours Mode"
          error={errorForField(errors, 'conditions.active_hours.mode')}
        >
          <select
            value={value.active_hours.mode}
            onChange={(e) =>
              setHours(
                'mode',
                e.target.value as ConditionsConfig['active_hours']['mode'],
              )
            }
            className={inputCls(
              !!errorForField(errors, 'conditions.active_hours.mode'),
            )}
          >
            <option value="always">Always (24/7)</option>
            <option value="fixed">Fixed Hours</option>
            <option value="sunset_sunrise">Sunset to Sunrise</option>
          </select>
        </Field>

        {/* Fixed hours sub-fields */}
        {value.active_hours.mode === 'fixed' && (
          <div className="mt-4 grid grid-cols-2 gap-4">
            <Field
              label="Start Time (HH:MM)"
              error={errorForField(errors, 'conditions.active_hours.start')}
            >
              <input
                type="time"
                value={value.active_hours.start}
                onChange={(e) => setHours('start', e.target.value)}
                className={inputCls(
                  !!errorForField(errors, 'conditions.active_hours.start'),
                )}
              />
            </Field>
            <Field
              label="End Time (HH:MM)"
              error={errorForField(errors, 'conditions.active_hours.end')}
            >
              <input
                type="time"
                value={value.active_hours.end}
                onChange={(e) => setHours('end', e.target.value)}
                className={inputCls(
                  !!errorForField(errors, 'conditions.active_hours.end'),
                )}
              />
            </Field>
          </div>
        )}

        {/* Sunset/Sunrise sub-fields */}
        {isSunsetMode && (
          <div className="mt-4 space-y-4">
            {/* City input */}
            <Field
              label="City"
              hint="Used for sunset/sunrise calculations. Leave blank to use latitude/longitude instead."
              error={errorForField(errors, 'conditions.city')}
            >
              <input
                type="text"
                value={value.city ?? ''}
                onChange={(e) =>
                  set('city', e.target.value || undefined)
                }
                placeholder="e.g. San Francisco"
                className={inputCls(!!errorForField(errors, 'conditions.city'))}
              />
            </Field>

            {/* Sunset / Sunrise offsets */}
            <div className="grid grid-cols-2 gap-4">
              <Field
                label="Sunset offset (minutes)"
                hint="-15 = 15 minutes before sunset"
                error={errorForField(
                  errors,
                  'conditions.sunset_offset_minutes',
                )}
              >
                <input
                  type="number"
                  value={value.sunset_offset_minutes ?? 0}
                  onChange={(e) =>
                    set('sunset_offset_minutes', Number(e.target.value))
                  }
                  step={5}
                  className={inputCls(
                    !!errorForField(
                      errors,
                      'conditions.sunset_offset_minutes',
                    ),
                  )}
                />
              </Field>
              <Field
                label="Sunrise offset (minutes)"
                hint="+15 = 15 minutes after sunrise"
                error={errorForField(
                  errors,
                  'conditions.sunrise_offset_minutes',
                )}
              >
                <input
                  type="number"
                  value={value.sunrise_offset_minutes ?? 0}
                  onChange={(e) =>
                    set('sunrise_offset_minutes', Number(e.target.value))
                  }
                  step={5}
                  className={inputCls(
                    !!errorForField(
                      errors,
                      'conditions.sunrise_offset_minutes',
                    ),
                  )}
                />
              </Field>
            </div>

            {/* Collapsible advanced lat/lon */}
            <div>
              <button
                type="button"
                onClick={() => setAdvancedOpen((o) => !o)}
                className="flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              >
                {advancedOpen ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
                Advanced — Latitude / Longitude
              </button>

              {advancedOpen && (
                <div className="mt-3 grid grid-cols-2 gap-4">
                  <Field
                    label="Latitude"
                    error={errorForField(errors, 'conditions.latitude')}
                  >
                    <input
                      type="number"
                      value={value.latitude}
                      onChange={(e) =>
                        set('latitude', Number(e.target.value))
                      }
                      min={-90}
                      max={90}
                      step={0.0001}
                      className={inputCls(
                        !!errorForField(errors, 'conditions.latitude'),
                      )}
                    />
                  </Field>
                  <Field
                    label="Longitude"
                    error={errorForField(errors, 'conditions.longitude')}
                  >
                    <input
                      type="number"
                      value={value.longitude}
                      onChange={(e) =>
                        set('longitude', Number(e.target.value))
                      }
                      min={-180}
                      max={180}
                      step={0.0001}
                      className={inputCls(
                        !!errorForField(errors, 'conditions.longitude'),
                      )}
                    />
                  </Field>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Per-camera schedules */}
      <div className="rounded-xl border border-gray-200 p-4 dark:border-gray-700/50">
        <h4 className="mb-1 text-sm font-semibold text-gray-800 dark:text-gray-200">
          Per-Camera Schedules
        </h4>
        <p className="mb-4 text-xs text-gray-500 dark:text-gray-400">
          Override the global active hours schedule for individual cameras.
          "Use global" means the camera follows the setting above.
        </p>

        {activeCameras.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-gray-500">
            No cameras are currently enabled in VoxWatch.
          </p>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-700/50">
            {activeCameras.map(([name, cfg]) => (
              <CameraScheduleRow
                key={name}
                cameraName={name}
                cameraConfig={cfg}
                onChange={(updated) => handleCameraChange(name, updated)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
