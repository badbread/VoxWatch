/**
 * MqttStep — MQTT broker credential configuration.
 *
 * Pre-fills from the probe result (host defaults to the Frigate host on port 1883).
 * If the probe already confirmed MQTT is reachable, a green checkmark and "Skip"
 * shortcut are shown so the user doesn't need to re-enter what already works.
 *
 * Username and password are optional — most local MQTT brokers don't need auth.
 */

import { useState } from 'react';
import {
  Radio,
  CheckCircle,
  AlertCircle,
  FlaskConical,
  Loader,
  ArrowRight,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { probeServices } from '@/api/setup';

/** Props for MqttStep. */
interface MqttStepProps {
  /** Current MQTT host (pre-filled from probe). */
  mqttHost: string;
  /** Current MQTT port. */
  mqttPort: number;
  /** Current username. */
  mqttUser: string;
  /** Current password. */
  mqttPassword: string;
  /** Current topic (usually "frigate/events"). */
  mqttTopic: string;
  /** Whether the probe already confirmed MQTT is reachable. */
  alreadyConnected: boolean;
  /** Frigate host for building the probe payload. */
  frigateHost: string;
  /** Called when the user saves MQTT settings and moves on. */
  onNext: (host: string, port: number, user: string, password: string, topic: string) => void;
}

const inputCls = cn(
  'w-full rounded-lg border bg-gray-800 px-3 py-3 text-base text-gray-100',
  'border-gray-600 placeholder-gray-500',
  'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50',
  'transition-colors',
);

/**
 * MQTT broker credentials form with optional test button.
 *
 * @example
 *   <MqttStep mqttHost="192.168.1.10" mqttPort={1883} ... />
 */
export function MqttStep({
  mqttHost: initialHost,
  mqttPort: initialPort,
  mqttUser: initialUser,
  mqttPassword: initialPassword,
  mqttTopic: initialTopic,
  alreadyConnected,
  frigateHost,
  onNext,
}: MqttStepProps) {
  const [host, setHost] = useState(initialHost);
  const [port, setPort] = useState(initialPort);
  const [user, setUser] = useState(initialUser);
  const [password, setPassword] = useState(initialPassword);
  const [topic, setTopic] = useState(initialTopic || 'frigate/events');

  const testMutation = useMutation({
    mutationFn: () =>
      probeServices({
        frigate_host: frigateHost,
        mqtt_host: host,
        mqtt_port: port,
        mqtt_user: user || undefined,
        mqtt_password: password || undefined,
      }),
  });

  const mqttReachable =
    alreadyConnected || (testMutation.isSuccess && testMutation.data.mqtt_reachable);

  const handleNext = () => {
    onNext(host, port, user, password, topic);
  };

  return (
    <div className="space-y-6 px-6 py-8">
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-purple-600/20 text-purple-400">
          <Radio className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-100">MQTT broker</h2>
          <p className="mt-1 text-sm text-gray-400">
            VoxWatch subscribes to Frigate events via MQTT. Most setups use the same host as Frigate.
          </p>
        </div>
      </div>

      {/* Already connected banner */}
      {alreadyConnected && (
        <div className="flex items-center gap-3 rounded-xl bg-green-900/30 border border-green-700/50 px-4 py-3">
          <CheckCircle className="h-5 w-5 shrink-0 text-green-400" />
          <div>
            <p className="text-sm font-semibold text-green-300">MQTT already connected</p>
            <p className="text-xs text-green-500">The probe confirmed your broker is reachable.</p>
          </div>
        </div>
      )}

      {/* Form fields */}
      <div className="space-y-4">
        {/* Host + Port row */}
        <div className="grid grid-cols-[1fr_auto] gap-3">
          <div>
            <label htmlFor="mqtt-host" className="mb-1.5 block text-sm font-medium text-gray-300">
              Broker hostname or IP
            </label>
            <input
              id="mqtt-host"
              type="text"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="192.168.1.10"
              autoComplete="off"
              className={inputCls}
            />
          </div>
          <div className="w-24">
            <label htmlFor="mqtt-port" className="mb-1.5 block text-sm font-medium text-gray-300">
              Port
            </label>
            <input
              id="mqtt-port"
              type="number"
              value={port}
              onChange={(e) => setPort(Number(e.target.value))}
              min={1}
              max={65535}
              className={inputCls}
            />
          </div>
        </div>

        {/* Credentials row */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="mqtt-user" className="mb-1.5 block text-sm font-medium text-gray-300">
              Username
              <span className="ml-1 text-gray-600 font-normal">(optional)</span>
            </label>
            <input
              id="mqtt-user"
              type="text"
              value={user}
              onChange={(e) => setUser(e.target.value)}
              placeholder="Leave blank if not required"
              autoComplete="off"
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="mqtt-pass" className="mb-1.5 block text-sm font-medium text-gray-300">
              Password
              <span className="ml-1 text-gray-600 font-normal">(optional)</span>
            </label>
            <input
              id="mqtt-pass"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Leave blank if not required"
              autoComplete="off"
              className={inputCls}
            />
          </div>
        </div>

        {/* Topic */}
        <div>
          <label htmlFor="mqtt-topic" className="mb-1.5 block text-sm font-medium text-gray-300">
            Frigate event topic
          </label>
          <input
            id="mqtt-topic"
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="frigate/events"
            autoComplete="off"
            className={inputCls}
          />
          <p className="mt-1 text-xs text-gray-500">
            Default is <span className="font-mono text-gray-400">frigate/events</span>. Only change this if you customised Frigate's MQTT config.
          </p>
        </div>
      </div>

      {/* Test connection button */}
      <button
        type="button"
        onClick={() => testMutation.mutate()}
        disabled={testMutation.isPending || !host}
        className={cn(
          'flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold',
          'border transition-all duration-150 active:scale-[0.98]',
          'focus:outline-none focus:ring-2 focus:ring-blue-500',
          'disabled:cursor-not-allowed disabled:opacity-50',
          mqttReachable
            ? 'border-green-600 bg-green-900/20 text-green-300'
            : testMutation.isSuccess && !testMutation.data.mqtt_reachable
              ? 'border-red-700 bg-red-950/20 text-red-300'
              : 'border-gray-600 bg-gray-800 text-gray-300 hover:bg-gray-700',
        )}
      >
        {testMutation.isPending ? (
          <Loader className="h-4 w-4 animate-spin" />
        ) : mqttReachable ? (
          <CheckCircle className="h-4 w-4" />
        ) : testMutation.isSuccess && !testMutation.data.mqtt_reachable ? (
          <AlertCircle className="h-4 w-4" />
        ) : (
          <FlaskConical className="h-4 w-4" />
        )}
        {testMutation.isPending
          ? 'Testing...'
          : mqttReachable
            ? 'Connected'
            : testMutation.isSuccess && !testMutation.data.mqtt_reachable
              ? 'Could not connect — check settings'
              : 'Test Connection'}
      </button>

      {/* Continue */}
      <button
        onClick={handleNext}
        disabled={!host}
        className={cn(
          'flex w-full items-center justify-center gap-3 rounded-xl px-6 py-4',
          'text-base font-semibold text-white',
          'transition-all duration-150 active:scale-[0.98]',
          'focus:outline-none focus:ring-2 focus:ring-blue-400',
          'disabled:cursor-not-allowed disabled:opacity-40',
          host ? 'bg-blue-600 hover:bg-blue-500' : 'bg-gray-700',
        )}
      >
        Continue
        <ArrowRight className="h-5 w-5" />
      </button>
    </div>
  );
}
