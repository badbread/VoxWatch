/**
 * Go2rtcConfigForm — form section for go2rtc connection settings.
 */

import { errorForField } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import type { Go2rtcConfig, ConfigValidationError } from '@/types/config';

export interface Go2rtcConfigFormProps {
  value: Go2rtcConfig;
  onChange: (value: Go2rtcConfig) => void;
  errors: ConfigValidationError[];
}

/**
 * go2rtc reverse-proxy connection settings form.
 */
export function Go2rtcConfigForm({
  value,
  onChange,
  errors,
}: Go2rtcConfigFormProps) {
  const set = <K extends keyof Go2rtcConfig>(k: K, v: Go2rtcConfig[K]) =>
    onChange({ ...value, [k]: v });

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        go2rtc media server connection. Used for pushing audio to camera
        backchannels.
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field
          label="go2rtc Host"
          error={errorForField(errors, 'go2rtc.host')}
        >
          <input
            type="text"
            value={value.host}
            onChange={(e) => set('host', e.target.value)}
            placeholder="localhost"
            className={inputCls(!!errorForField(errors, 'go2rtc.host'))}
          />
        </Field>
        <Field
          label="go2rtc API Port"
          error={errorForField(errors, 'go2rtc.api_port')}
        >
          <input
            type="number"
            value={value.api_port}
            onChange={(e) => set('api_port', Number(e.target.value))}
            min={1}
            max={65535}
            className={inputCls(!!errorForField(errors, 'go2rtc.api_port'))}
          />
        </Field>
      </div>
    </div>
  );
}
