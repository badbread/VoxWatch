/**
 * FrigateStep — "Where is Frigate running?" connection step.
 *
 * The user enters a Frigate hostname or IP. The port input is hidden
 * inside an "Advanced" collapsible so the common case (port 5000) stays
 * out of the way. Clicking "Connect" fires POST /api/setup/probe.
 *
 * If FRIGATE_HOST was set as a Docker environment variable, the host input
 * is pre-filled via setupStatus.frigate_host_env so most Docker Compose users
 * land here with the field already filled in.
 */

import { useState } from 'react';
import { Server, ChevronDown, ChevronUp, Loader, ArrowRight, AlertCircle } from 'lucide-react';
import { cn } from '@/utils/cn';

/** Props for FrigateStep. */
interface FrigateStepProps {
  /** Initial host value — may be pre-filled from FRIGATE_HOST env. */
  initialHost: string;
  /** Initial port value (default 5000). */
  initialPort: number;
  /** Whether a probe request is currently in-flight. */
  isProbing: boolean;
  /** Error message to display when the probe failed. */
  probeError: string | null;
  /**
   * Called when the user clicks Connect.
   * @param host - Frigate hostname or IP
   * @param port - Frigate API port
   */
  onConnect: (host: string, port: number) => void;
}

/** Input field style — matches the global inputCls pattern. */
const inputCls = cn(
  'w-full rounded-lg border bg-gray-800 px-3 py-3 text-base text-gray-100',
  'border-gray-600 placeholder-gray-500',
  'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50',
  'transition-colors',
);

/**
 * Frigate connection form with host input and optional advanced port override.
 *
 * @example
 *   <FrigateStep
 *     initialHost="192.168.1.10"
 *     initialPort={5000}
 *     isProbing={false}
 *     probeError={null}
 *     onConnect={(host, port) => dispatch(probe({ frigateHost: host, frigatePort: port }))}
 *   />
 */
export function FrigateStep({
  initialHost,
  initialPort,
  isProbing,
  probeError,
  onConnect,
}: FrigateStepProps) {
  const [host, setHost] = useState(initialHost);
  const [port, setPort] = useState(initialPort);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const canConnect = host.trim().length > 0 && !isProbing;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (canConnect) {
      onConnect(host.trim(), port);
    }
  };

  return (
    <div className="space-y-6 px-6 py-8">
      {/* Step header */}
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600/20 text-blue-400">
          <Server className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-100">Where is Frigate running?</h2>
          <p className="mt-1 text-sm text-gray-400">
            Enter the hostname or IP address of your Frigate NVR.
            VoxWatch will probe it automatically.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Host input */}
        <div>
          <label
            htmlFor="frigate-host"
            className="mb-1.5 block text-sm font-medium text-gray-300"
          >
            Frigate hostname or IP
          </label>
          <input
            id="frigate-host"
            type="text"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="192.168.1.10 or frigate.home"
            autoFocus
            autoComplete="off"
            spellCheck={false}
            className={inputCls}
          />
          <p className="mt-1 text-xs text-gray-500">
            This is the machine running Frigate — usually your NVR or a server.
          </p>
        </div>

        {/* Advanced — port override */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-300 transition-colors focus:outline-none"
          >
            {showAdvanced ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
            Advanced options
          </button>

          {showAdvanced && (
            <div className="mt-3">
              <label
                htmlFor="frigate-port"
                className="mb-1.5 block text-sm font-medium text-gray-300"
              >
                Frigate API port
              </label>
              <input
                id="frigate-port"
                type="number"
                value={port}
                onChange={(e) => setPort(Number(e.target.value))}
                min={1}
                max={65535}
                className={cn(inputCls, 'w-32')}
              />
              <p className="mt-1 text-xs text-gray-500">Default is 5000.</p>
            </div>
          )}
        </div>

        {/* Error feedback */}
        {probeError && (
          <div className="flex items-start gap-2 rounded-lg bg-red-950/40 px-4 py-3 text-sm text-red-300 border border-red-800/50">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{probeError}</span>
          </div>
        )}

        {/* Connect button */}
        <button
          type="submit"
          disabled={!canConnect}
          className={cn(
            'flex w-full items-center justify-center gap-3 rounded-xl px-6 py-4',
            'text-base font-semibold text-white',
            'transition-all duration-150 active:scale-[0.98]',
            'focus:outline-none focus:ring-2 focus:ring-blue-400',
            'disabled:cursor-not-allowed disabled:opacity-50',
            canConnect && !isProbing
              ? 'bg-blue-600 hover:bg-blue-500'
              : 'bg-blue-700',
          )}
        >
          {isProbing ? (
            <>
              <Loader className="h-5 w-5 animate-spin" />
              Connecting...
            </>
          ) : (
            <>
              Connect
              <ArrowRight className="h-5 w-5" />
            </>
          )}
        </button>
      </form>
    </div>
  );
}
