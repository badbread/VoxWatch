/**
 * LoggingConfigForm — log level and log file path settings.
 */

import { errorForField } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import type { LoggingConfig, ConfigValidationError } from '@/types/config';

export interface LoggingConfigFormProps {
  value: LoggingConfig;
  onChange: (value: LoggingConfig) => void;
  errors: ConfigValidationError[];
}

const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'];

/**
 * Logging configuration form with level dropdown and file path input.
 */
export function LoggingConfigForm({
  value,
  onChange,
  errors,
}: LoggingConfigFormProps) {
  const set = <K extends keyof LoggingConfig>(k: K, v: LoggingConfig[K]) =>
    onChange({ ...value, [k]: v });

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Log output goes to both stdout and the configured file. Use DEBUG
        sparingly — it produces verbose output that may impact performance.
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Log Level" error={errorForField(errors, 'logging.level')}>
          <select
            value={value.level}
            onChange={(e) => set('level', e.target.value)}
            className={inputCls(!!errorForField(errors, 'logging.level'))}
          >
            {LOG_LEVELS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Log File Path"
          error={errorForField(errors, 'logging.file')}
          hint="Absolute path inside the container"
        >
          <input
            type="text"
            value={value.file}
            onChange={(e) => set('file', e.target.value)}
            placeholder="/data/voxwatch.log"
            className={inputCls(!!errorForField(errors, 'logging.file'))}
          />
        </Field>
      </div>
    </div>
  );
}
