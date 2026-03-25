/**
 * ConditionsConfigForm — detection trigger conditions settings.
 *
 * Covers: min_score slider, cooldown_seconds, active_hours mode with
 * conditional sub-fields for fixed/sunset_sunrise modes.
 */

import { errorForField } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import { formatScore } from '@/utils/formatters';
import type { ConditionsConfig, ConfigValidationError } from '@/types/config';

export interface ConditionsConfigFormProps {
  value: ConditionsConfig;
  onChange: (value: ConditionsConfig) => void;
  errors: ConfigValidationError[];
}

/**
 * Detection trigger conditions form.
 */
export function ConditionsConfigForm({
  value,
  onChange,
  errors,
}: ConditionsConfigFormProps) {
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

      {/* Active hours mode */}
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

        {/* Lat/lng for sunset_sunrise */}
        {value.active_hours.mode === 'sunset_sunrise' && (
          <div className="mt-4 grid grid-cols-2 gap-4">
            <Field
              label="Latitude"
              error={errorForField(errors, 'conditions.latitude')}
            >
              <input
                type="number"
                value={value.latitude}
                onChange={(e) => set('latitude', Number(e.target.value))}
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
                onChange={(e) => set('longitude', Number(e.target.value))}
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
  );
}
