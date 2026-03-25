/**
 * FrigateConfigForm — form section for Frigate NVR connection settings.
 */

import { errorForField } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import type { FrigateConfig } from '@/types/config';
import type { ConfigValidationError } from '@/types/config';

export interface FrigateConfigFormProps {
  value: FrigateConfig;
  onChange: (value: FrigateConfig) => void;
  errors: ConfigValidationError[];
}

/**
 * Frigate NVR connection settings form.
 */
export function FrigateConfigForm({
  value,
  onChange,
  errors,
}: FrigateConfigFormProps) {
  const set = <K extends keyof FrigateConfig>(
    key: K,
    v: FrigateConfig[K],
  ) => onChange({ ...value, [key]: v });

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Frigate NVR connection and MQTT broker settings.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field
          label="Frigate Host"
          error={errorForField(errors, 'frigate.host')}
        >
          <input
            type="text"
            value={value.host}
            onChange={(e) => set('host', e.target.value)}
            placeholder="localhost"
            className={inputCls(!!errorForField(errors, 'frigate.host'))}
          />
        </Field>
        <Field
          label="Frigate Port"
          error={errorForField(errors, 'frigate.port')}
        >
          <input
            type="number"
            value={value.port}
            onChange={(e) => set('port', Number(e.target.value))}
            min={1}
            max={65535}
            className={inputCls(!!errorForField(errors, 'frigate.port'))}
          />
        </Field>
        <Field
          label="MQTT Host"
          error={errorForField(errors, 'frigate.mqtt_host')}
        >
          <input
            type="text"
            value={value.mqtt_host}
            onChange={(e) => set('mqtt_host', e.target.value)}
            placeholder="localhost"
            className={inputCls(!!errorForField(errors, 'frigate.mqtt_host'))}
          />
        </Field>
        <Field
          label="MQTT Port"
          error={errorForField(errors, 'frigate.mqtt_port')}
        >
          <input
            type="number"
            value={value.mqtt_port}
            onChange={(e) => set('mqtt_port', Number(e.target.value))}
            min={1}
            max={65535}
            className={inputCls(!!errorForField(errors, 'frigate.mqtt_port'))}
          />
        </Field>
        <Field
          label="MQTT Topic"
          error={errorForField(errors, 'frigate.mqtt_topic')}
          className="sm:col-span-2"
        >
          <input
            type="text"
            value={value.mqtt_topic}
            onChange={(e) => set('mqtt_topic', e.target.value)}
            placeholder="frigate/events"
            className={inputCls(!!errorForField(errors, 'frigate.mqtt_topic'))}
          />
        </Field>
        <Field label="MQTT Username (optional)">
          <input
            type="text"
            value={value.mqtt_user ?? ''}
            onChange={(e) =>
              set('mqtt_user', e.target.value || undefined)
            }
            autoComplete="username"
            className={inputCls(false)}
          />
        </Field>
        <Field label="MQTT Password (optional)">
          <input
            type="password"
            value={value.mqtt_password ?? ''}
            onChange={(e) =>
              set('mqtt_password', e.target.value || undefined)
            }
            autoComplete="current-password"
            className={inputCls(false)}
          />
        </Field>
      </div>
    </div>
  );
}

