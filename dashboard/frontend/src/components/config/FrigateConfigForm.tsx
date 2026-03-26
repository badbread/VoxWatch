/**
 * FrigateConfigForm — form section for Frigate NVR connection settings.
 *
 * Includes inline "Test Connection" buttons for both Frigate and MQTT
 * that hit the backend test endpoints and show pass/fail results.
 */

import { useMutation } from '@tanstack/react-query';
import { CheckCircle2, XCircle, Loader2, Wifi } from 'lucide-react';
import { errorForField } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import { testFrigate, testMqtt } from '@/api/setup';
import type { TestServiceResult } from '@/api/setup';
import type { FrigateConfig } from '@/types/config';
import type { ConfigValidationError } from '@/types/config';
import { cn } from '@/utils/cn';

export interface FrigateConfigFormProps {
  value: FrigateConfig;
  onChange: (value: FrigateConfig) => void;
  errors: ConfigValidationError[];
}

/**
 * Inline test result badge — shows success/failure with message.
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
 * Frigate NVR connection settings form with Frigate + MQTT test buttons.
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

  const frigateMutation = useMutation({
    mutationFn: () => testFrigate(value.host, value.port),
  });

  const mqttMutation = useMutation({
    mutationFn: () => testMqtt(
      value.mqtt_host,
      value.mqtt_port,
      value.mqtt_user,
      value.mqtt_password,
    ),
  });

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
      </div>

      {/* Frigate test button */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => frigateMutation.mutate()}
          disabled={frigateMutation.isPending || !value.host}
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
          Test Frigate
        </button>
        <TestResultBadge
          result={frigateMutation.data}
          isPending={frigateMutation.isPending}
        />
      </div>

      <hr className="border-gray-200 dark:border-gray-700/50" />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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

      {/* MQTT test button */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => mqttMutation.mutate()}
          disabled={mqttMutation.isPending || !value.mqtt_host}
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
          Test MQTT
        </button>
        <TestResultBadge
          result={mqttMutation.data}
          isPending={mqttMutation.isPending}
        />
      </div>
    </div>
  );
}
