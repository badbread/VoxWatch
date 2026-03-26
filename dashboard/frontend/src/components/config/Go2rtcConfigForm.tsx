/**
 * Go2rtcConfigForm — form section for go2rtc connection settings.
 *
 * Includes an inline "Test go2rtc" button that hits the backend test endpoint
 * and shows pass/fail results, matching the pattern used in FrigateConfigForm.
 */

import { useMutation } from '@tanstack/react-query';
import { CheckCircle2, XCircle, Loader2, Wifi } from 'lucide-react';
import { errorForField } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import { testGo2rtc } from '@/api/setup';
import type { TestServiceResult } from '@/api/setup';
import type { Go2rtcConfig, ConfigValidationError } from '@/types/config';
import { cn } from '@/utils/cn';

export interface Go2rtcConfigFormProps {
  value: Go2rtcConfig;
  onChange: (value: Go2rtcConfig) => void;
  errors: ConfigValidationError[];
}

/**
 * Inline test result badge — shows success/failure with message and latency.
 */
function TestResultBadge({ result, isPending }: { result: TestServiceResult | undefined; isPending: boolean }) {
  if (isPending) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-blue-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Testing...
      </span>
    );
  }
  if (!result) return null;
  return (
    <span
      className={cn(
        'flex items-center gap-1.5 text-xs',
        result.ok ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400',
      )}
    >
      {result.ok ? (
        <CheckCircle2 className="h-3.5 w-3.5" />
      ) : (
        <XCircle className="h-3.5 w-3.5" />
      )}
      {result.message}
      {result.latency_ms != null && result.ok && (
        <span className="text-gray-400"> ({result.latency_ms}ms)</span>
      )}
    </span>
  );
}

/**
 * go2rtc reverse-proxy connection settings form with inline connectivity test.
 */
export function Go2rtcConfigForm({
  value,
  onChange,
  errors,
}: Go2rtcConfigFormProps) {
  const set = <K extends keyof Go2rtcConfig>(k: K, v: Go2rtcConfig[K]) =>
    onChange({ ...value, [k]: v });

  const go2rtcMutation = useMutation({
    mutationFn: () => testGo2rtc(value.host, value.api_port),
  });

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

      {/* go2rtc test button */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => go2rtcMutation.mutate()}
          disabled={go2rtcMutation.isPending || !value.host}
          className={cn(
            'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium',
            'border border-gray-300 bg-white text-gray-700',
            'hover:bg-gray-50 hover:border-gray-400',
            'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300',
            'dark:hover:bg-gray-700 dark:hover:border-gray-500',
            'disabled:opacity-40 disabled:cursor-not-allowed',
            'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
          )}
        >
          <Wifi className="h-3.5 w-3.5" />
          Test go2rtc
        </button>
        <TestResultBadge
          result={go2rtcMutation.data}
          isPending={go2rtcMutation.isPending}
        />
      </div>
    </div>
  );
}
