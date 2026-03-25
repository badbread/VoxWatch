/**
 * TestsPage — unified testing and diagnostics panel.
 *
 * Consolidates all manual testing tools into one page with five collapsible
 * sections so operators can work through the full audio pipeline from TTS
 * synthesis down to camera backchannel delivery without switching pages.
 *
 * Sections:
 *   1. Audio Push Test  — quick-fire camera buttons (wraps TestAudioButton)
 *   2. TTS Voice Test   — generate a preview clip via the current TTS engine
 *   3. Camera Compatibility — check backchannel support per camera
 *   4. MQTT Simulation  — info card for the CLI test script
 *   5. Service Logs     — tail /data/voxwatch.log with level filtering
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  Volume2,
  Mic2,
  Camera,
  Terminal,
  FileText,
  ChevronDown,
  ChevronUp,
  Play,
  Loader,
  CheckCircle,
  XCircle,
  RefreshCw,
  AlertTriangle,
  Info,
  ExternalLink,
} from 'lucide-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { TestAudioButton } from '@/components/audio/TestAudioButton';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { CameraReportPrompt } from '@/components/common/CameraReportPrompt';
import { useServiceStatus } from '@/hooks/useServiceStatus';
import { getConfig } from '@/api/config';
import { testAudio } from '@/api/audio';
import { previewAudio } from '@/api/status';
import { getLogs } from '@/api/system';
import type { LogEntry } from '@/api/system';
import type { CameraStatus } from '@/types/status';

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/**
 * Map a log level string to a Tailwind text-color class for the log viewer.
 *
 * @param level - Severity level from the parsed log entry.
 * @returns Tailwind class string for the level badge.
 */
function levelClass(level: string): string {
  switch (level) {
    case 'ERROR':
    case 'CRITICAL':
      return 'text-red-600 dark:text-red-400';
    case 'WARNING':
      return 'text-yellow-600 dark:text-yellow-400';
    case 'INFO':
      return 'text-blue-600 dark:text-blue-400';
    case 'DEBUG':
      return 'text-gray-400 dark:text-gray-500';
    default:
      return 'text-gray-500 dark:text-gray-400';
  }
}

/**
 * Map a log level to a compact badge background for the log viewer.
 *
 * @param level - Severity level from the parsed log entry.
 * @returns Tailwind class string for the badge background.
 */
function levelBadgeClass(level: string): string {
  switch (level) {
    case 'ERROR':
    case 'CRITICAL':
      return 'bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400';
    case 'WARNING':
      return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-950/40 dark:text-yellow-400';
    case 'INFO':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400';
    case 'DEBUG':
      return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400';
    default:
      return 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500';
  }
}

// ---------------------------------------------------------------------------
// Section card wrapper
// ---------------------------------------------------------------------------

interface SectionCardProps {
  /** Icon rendered in the section header. */
  icon: React.ElementType;
  /** Section title text. */
  title: string;
  /** Short description rendered below the title when the section is collapsed. */
  description: string;
  /** Whether the section body is visible. */
  open: boolean;
  /** Fired when the user clicks the header to toggle open/closed. */
  onToggle: () => void;
  /** Content rendered inside the collapsible body. */
  children: React.ReactNode;
  /** Optional extra content shown inline in the header (right side). */
  headerExtra?: React.ReactNode;
}

/**
 * Collapsible section card used to group each test tool.
 *
 * Renders a header with icon, title, toggle chevron, and an optional
 * right-side element (e.g. a status badge). Body slides in/out via
 * CSS display toggling — no animation library required.
 */
function SectionCard({
  icon: Icon,
  title,
  description,
  open,
  onToggle,
  children,
  headerExtra,
}: SectionCardProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700/50 dark:bg-gray-900">
      {/* Header — always visible, click to toggle */}
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          'flex w-full items-start gap-3 px-5 py-4 text-left',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset',
          open ? 'border-b border-gray-100 dark:border-gray-700/50' : '',
        )}
        aria-expanded={open}
      >
        <span className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-blue-50 dark:bg-blue-950/40">
          <Icon className="h-4 w-4 text-blue-600 dark:text-blue-400" aria-hidden="true" />
        </span>

        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{title}</p>
          {!open && (
            <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{description}</p>
          )}
        </div>

        {headerExtra && <div className="flex-shrink-0">{headerExtra}</div>}

        <span className="ml-2 flex-shrink-0 text-gray-400 dark:text-gray-500">
          {open ? (
            <ChevronUp className="h-4 w-4" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-4 w-4" aria-hidden="true" />
          )}
        </span>
      </button>

      {/* Collapsible body */}
      {open && <div className="px-5 py-4">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 2: TTS Voice Test
// ---------------------------------------------------------------------------

/** Available MQTT test scenarios with human-readable descriptions. */
const TTS_DEFAULT_MESSAGE =
  "This is a private property. You are being recorded. Please leave immediately.";

/**
 * TTS Voice Test section body.
 *
 * Reads the current TTS engine from config and calls POST /api/audio/preview
 * to generate an audio clip that is played in the browser (no camera needed).
 *
 * @param ttsEngine - The engine string from the loaded config (e.g. "kokoro").
 * @param ttsVoice  - The voice ID / model name from config.
 */
function TtsVoiceTestSection({
  ttsEngine,
  ttsVoice,
}: {
  ttsEngine: string;
  ttsVoice: string;
}) {
  const [text, setText] = useState(TTS_DEFAULT_MESSAGE);
  const [generationMs, setGenerationMs] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const previewMutation = useMutation({
    mutationFn: () =>
      previewAudio({
        persona: 'default',
        voice: ttsVoice,
        provider: ttsEngine,
        message: text.trim() || TTS_DEFAULT_MESSAGE,
      }),
    onSuccess: ({ blob, generationTimeMs }) => {
      setGenerationMs(generationTimeMs);
      // Release any previously created object URL to avoid memory leaks.
      if (audioRef.current?.src) {
        URL.revokeObjectURL(audioRef.current.src);
      }
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.play().catch(() => {
        // Browser may block autoplay — the user can click play on the <audio> element.
      });
    },
  });

  return (
    <div className="space-y-4">
      {/* Current provider info banner */}
      <div className="flex items-start gap-2 rounded-lg bg-blue-50 px-3 py-2.5 text-xs dark:bg-blue-950/30">
        <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-blue-500" aria-hidden="true" />
        <span className="text-blue-700 dark:text-blue-300">
          Using engine <strong>{ttsEngine || 'not configured'}</strong>
          {ttsVoice ? (
            <>
              {' '}with voice <strong>{ttsVoice}</strong>
            </>
          ) : null}
          . Change the engine in{' '}
          <Link
            to="/config"
            className="underline hover:no-underline"
            onClick={(e) => e.stopPropagation()}
          >
            Configuration
          </Link>
          .
        </span>
      </div>

      {/* Message input */}
      <div>
        <label
          htmlFor="tts-preview-text"
          className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
        >
          Message to synthesize
        </label>
        <textarea
          id="tts-preview-text"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className={cn(
            'w-full resize-none rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm',
            'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500',
            'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
          )}
          placeholder={TTS_DEFAULT_MESSAGE}
        />
      </div>

      {/* Generate button */}
      <button
        type="button"
        onClick={() => previewMutation.mutate()}
        disabled={previewMutation.isPending || !ttsEngine}
        className={cn(
          'flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold text-white',
          'transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'bg-blue-600 hover:bg-blue-700',
        )}
      >
        {previewMutation.isPending ? (
          <Loader className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Play className="h-4 w-4" aria-hidden="true" />
        )}
        {previewMutation.isPending ? 'Generating...' : 'Generate & Play'}
      </button>

      {/* Result feedback */}
      {previewMutation.isSuccess && generationMs !== null && (
        <p className="flex items-center gap-1.5 text-xs text-green-700 dark:text-green-400">
          <CheckCircle className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          Generated in {generationMs}ms — playing in browser.
        </p>
      )}

      {previewMutation.isError && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2.5 text-xs text-red-700 dark:bg-red-950/20 dark:text-red-400">
          <XCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          <span>
            Preview failed — check that the TTS server is reachable and the engine is
            configured correctly.
          </span>
        </div>
      )}

      {!ttsEngine && (
        <div className="flex items-start gap-2 rounded-lg bg-yellow-50 px-3 py-2.5 text-xs text-yellow-700 dark:bg-yellow-950/30 dark:text-yellow-400">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          <span>No TTS engine configured. Add a TTS section in Configuration first.</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 3: Camera Compatibility Test
// ---------------------------------------------------------------------------

/**
 * Camera Compatibility Test section body.
 *
 * Lets the operator select a camera and push a test tone via the normal audio
 * push path, then shows backchannel codec info sourced from the status API.
 *
 * After a test completes on a camera that is not in the VoxWatch database
 * (speaker_status === 'unknown' or undefined), a CameraReportPrompt appears
 * so the operator can file a community compatibility report in two clicks.
 */
function CameraCompatibilitySection({
  cameras,
  frigateVersion,
  go2rtcVersion,
}: {
  cameras: CameraStatus[];
  frigateVersion?: string | undefined;
  go2rtcVersion?: string | undefined;
}) {
  const [selected, setSelected] = useState('');

  const selectedCamera = cameras.find((c) => c.name === selected) ?? null;

  // True when the currently selected camera is not in the VoxWatch database
  const isUnknownCamera =
    !selectedCamera?.speaker_status ||
    selectedCamera.speaker_status === 'unknown';

  const testMutation = useMutation({
    mutationFn: () =>
      testAudio({
        camera_name: selected,
        message: 'Backchannel test. If you hear this, audio is working.',
      }),
  });

  return (
    <div className="space-y-4">
      {/* Camera selector */}
      <div>
        <label
          htmlFor="compat-camera-select"
          className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
        >
          Camera to test
        </label>
        <select
          id="compat-camera-select"
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            testMutation.reset();
          }}
          className={cn(
            'w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm',
            'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500',
            'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
          )}
        >
          <option value="">Select a camera...</option>
          {cameras.map((cam) => (
            <option key={cam.name} value={cam.name}>
              {cam.name}{!cam.enabled ? ' (not configured)' : ''}
            </option>
          ))}
        </select>
      </div>

      {/* Info panel for selected camera */}
      {selectedCamera && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs dark:border-gray-700/50 dark:bg-gray-800/50">
          <p className="mb-2 font-semibold text-gray-700 dark:text-gray-300">
            Camera info
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-gray-600 dark:text-gray-400">
            <dt>Enabled</dt>
            <dd className={selectedCamera.enabled ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}>
              {selectedCamera.enabled ? 'Yes' : 'No'}
            </dd>

            <dt>Frigate online</dt>
            <dd className={selectedCamera.frigate_online ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}>
              {selectedCamera.frigate_online === undefined ? 'Unknown' : selectedCamera.frigate_online ? 'Yes' : 'No'}
            </dd>

            <dt>Backchannel</dt>
            <dd className={selectedCamera.has_backchannel ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}>
              {selectedCamera.has_backchannel === undefined
                ? 'Unknown'
                : selectedCamera.has_backchannel
                  ? 'Supported'
                  : 'Not detected'}
            </dd>

            {selectedCamera.backchannel_codecs && selectedCamera.backchannel_codecs.length > 0 && (
              <>
                <dt>Codecs</dt>
                <dd className="font-mono">{selectedCamera.backchannel_codecs.join(', ')}</dd>
              </>
            )}

            {selectedCamera.camera_manufacturer && (
              <>
                <dt>Manufacturer</dt>
                <dd>{selectedCamera.camera_manufacturer}</dd>
              </>
            )}

            {selectedCamera.camera_model && (
              <>
                <dt>Model</dt>
                <dd>{selectedCamera.camera_model}</dd>
              </>
            )}

            {selectedCamera.speaker_status && (
              <>
                <dt>Speaker</dt>
                <dd>{selectedCamera.speaker_status}</dd>
              </>
            )}
          </dl>
        </div>
      )}

      {/* Test button */}
      <button
        type="button"
        onClick={() => testMutation.mutate()}
        disabled={!selected || testMutation.isPending}
        className={cn(
          'flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold text-white',
          'transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'bg-blue-600 hover:bg-blue-700',
        )}
      >
        {testMutation.isPending ? (
          <Loader className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Volume2 className="h-4 w-4" aria-hidden="true" />
        )}
        {testMutation.isPending ? 'Pushing audio...' : 'Test Backchannel'}
      </button>

      {/* Result */}
      {testMutation.isSuccess && testMutation.data && (
        <div
          className={cn(
            'flex items-start gap-2 rounded-lg px-3 py-2.5 text-xs',
            testMutation.data.success
              ? 'bg-green-50 text-green-700 dark:bg-green-950/20 dark:text-green-400'
              : 'bg-red-50 text-red-700 dark:bg-red-950/20 dark:text-red-400',
          )}
        >
          {testMutation.data.success ? (
            <CheckCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          ) : (
            <XCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          )}
          <span>{testMutation.data.message}</span>
        </div>
      )}

      {/* Community report prompt — appears after a test on an unknown camera */}
      {testMutation.isSuccess && isUnknownCamera && selectedCamera && (
        <CameraReportPrompt
          cameraName={selectedCamera.name}
          manufacturer={selectedCamera.camera_manufacturer}
          model={selectedCamera.camera_model}
          backchannelCodecs={selectedCamera.backchannel_codecs}
          hasBackchannel={selectedCamera.has_backchannel}
          audioResult={testMutation.data?.success ? 'success' : 'failed'}
          frigateVersion={frigateVersion}
          go2rtcVersion={go2rtcVersion}
        />
      )}

      {/* Link to Setup Wizard for full test */}
      <p className="text-xs text-gray-500 dark:text-gray-400">
        For a full guided compatibility test including ONVIF discovery and codec
        validation, use the{' '}
        <Link
          to="/wizard"
          className="text-blue-600 underline hover:no-underline dark:text-blue-400"
        >
          Setup Wizard
          <ExternalLink className="ml-0.5 inline h-3 w-3" aria-hidden="true" />
        </Link>
        .
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 4: MQTT Simulation
// ---------------------------------------------------------------------------

/** Scenarios available in the MQTT simulation script with their descriptions. */
const MQTT_SCENARIOS: Array<{ name: string; description: string }> = [
  { name: 'car_thief_night', description: 'Person approaching a vehicle at night — triggers full AI deterrent pipeline.' },
  { name: 'package_thief', description: 'Porch pirate pickup scenario with escalation response.' },
  { name: 'person_loitering', description: 'Person lingering near a door for extended time.' },
  { name: 'driveway_entry', description: 'Unknown person walking up the driveway.' },
  { name: 'backyard_intrusion', description: 'Detection in a rear zone during active hours.' },
];

/**
 * MQTT Simulation section body.
 *
 * This is informational only — the actual simulation runs as a CLI script.
 * The section shows the command and lists available scenarios so the operator
 * can copy-paste without looking up the docs.
 */
function MqttSimulationSection({ cameras }: { cameras: CameraStatus[] }) {
  const [selectedCamera, setSelectedCamera] = useState(cameras[0]?.name ?? 'frontdoor');
  const [selectedScenario, setSelectedScenario] = useState('car_thief_night');

  const command = `python tests/test_mqtt_simulation.py --scenario ${selectedScenario} --camera ${selectedCamera}`;

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(command);
    } catch {
      // Clipboard API unavailable — user can select manually.
    }
  }, [command]);

  // Run simulation directly from the dashboard via backend API
  const simMutation = useMutation({
    mutationFn: async () => {
      const { data } = await (await import('@/api/client')).default.post('/api/system/mqtt-simulation', {
        camera: selectedCamera,
        scenario: selectedScenario,
        score: 0.92,
      });
      return data as { success: boolean; event_id: string; message: string };
    },
  });

  return (
    <div className="space-y-4">
      {/* Info banner */}
      <div className="flex items-start gap-2 rounded-lg bg-blue-50 px-3 py-2.5 text-xs dark:bg-blue-950/30">
        <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-blue-500" aria-hidden="true" />
        <span className="text-blue-700 dark:text-blue-300">
          The MQTT simulation script publishes a synthetic Frigate event to the broker so you
          can test the full detection pipeline — AI analysis, TTS generation, and audio push —
          without a real person in front of a camera. Run it from the VoxWatch container or
          host machine.
        </span>
      </div>

      {/* Scenario selector */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label
            htmlFor="mqtt-scenario"
            className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
          >
            Scenario
          </label>
          <select
            id="mqtt-scenario"
            value={selectedScenario}
            onChange={(e) => setSelectedScenario(e.target.value)}
            className={cn(
              'w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm',
              'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500',
              'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
            )}
          >
            {MQTT_SCENARIOS.map((s) => (
              <option key={s.name} value={s.name}>{s.name}</option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="mqtt-camera"
            className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
          >
            Camera name
          </label>
          {cameras.length > 0 ? (
            <select
              id="mqtt-camera"
              value={selectedCamera}
              onChange={(e) => setSelectedCamera(e.target.value)}
              className={cn(
                'w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm',
                'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500',
                'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
              )}
            >
              {cameras.map((c) => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
          ) : (
            <input
              id="mqtt-camera"
              type="text"
              value={selectedCamera}
              onChange={(e) => setSelectedCamera(e.target.value)}
              placeholder="frontdoor"
              className={cn(
                'w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm',
                'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500',
                'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
              )}
            />
          )}
        </div>
      </div>

      {/* Generated command */}
      <div>
        <p className="mb-1 text-xs font-medium text-gray-700 dark:text-gray-300">
          Command to run
        </p>
        <div className="group relative">
          <pre className="overflow-x-auto rounded-lg bg-gray-900 px-4 py-3 text-xs text-green-400 dark:bg-gray-950">
            {command}
          </pre>
          <button
            type="button"
            onClick={handleCopy}
            className={cn(
              'absolute right-2 top-2 rounded px-2 py-1 text-xs text-gray-400 transition-colors',
              'hover:bg-gray-700 hover:text-gray-100',
              'opacity-0 group-hover:opacity-100',
            )}
          >
            Copy
          </button>
        </div>
      </div>

      {/* Run Simulation button */}
      <button
        type="button"
        onClick={() => simMutation.mutate()}
        disabled={simMutation.isPending}
        className={cn(
          'flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold text-white transition-all',
          'active:scale-[0.98]',
          'focus:outline-none focus:ring-2 focus:ring-blue-500',
          'disabled:cursor-not-allowed disabled:opacity-50',
          simMutation.isSuccess && simMutation.data?.success
            ? 'bg-green-600 hover:bg-green-700'
            : 'bg-blue-600 hover:bg-blue-700',
        )}
      >
        {simMutation.isPending ? (
          <Loader className="h-4 w-4 animate-spin" />
        ) : simMutation.isSuccess && simMutation.data?.success ? (
          <CheckCircle className="h-4 w-4" />
        ) : (
          <Play className="h-4 w-4" />
        )}
        {simMutation.isPending
          ? 'Publishing event...'
          : simMutation.isSuccess && simMutation.data?.success
            ? `Triggered — ${simMutation.data.event_id.slice(0, 20)}...`
            : 'Run Simulation'}
      </button>

      {/* Result feedback */}
      {simMutation.isSuccess && !simMutation.data?.success && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2.5 text-xs dark:bg-red-950/30">
          <XCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-red-500" />
          <span className="text-red-700 dark:text-red-300">{simMutation.data?.message}</span>
        </div>
      )}

      {simMutation.isSuccess && simMutation.data?.success && (
        <div className="flex items-start gap-2 rounded-lg bg-green-50 px-3 py-2.5 text-xs dark:bg-green-950/30">
          <CheckCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-green-500" />
          <span className="text-green-700 dark:text-green-300">
            VoxWatch should now be processing the event. Check the Service Logs section below
            for pipeline progress, and listen for audio on the {selectedCamera} camera speaker.
          </span>
        </div>
      )}

      {/* Scenario descriptions */}
      <div>
        <p className="mb-2 text-xs font-medium text-gray-700 dark:text-gray-300">
          Available scenarios
        </p>
        <ul className="space-y-1.5">
          {MQTT_SCENARIOS.map((s) => (
            <li key={s.name} className="flex gap-2 text-xs">
              <span
                className={cn(
                  'mt-0.5 inline-block rounded px-1.5 py-0.5 font-mono text-[10px] font-medium leading-none',
                  s.name === selectedScenario
                    ? 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400'
                    : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
                )}
              >
                {s.name}
              </span>
              <span className="text-gray-600 dark:text-gray-400">{s.description}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 5: Service Logs
// ---------------------------------------------------------------------------

/** Level filter options shown in the logs section. */
const LOG_LEVELS = ['all', 'DEBUG', 'INFO', 'WARNING', 'ERROR'] as const;
type LogLevel = (typeof LOG_LEVELS)[number];

/**
 * Service Logs section body.
 *
 * Reads the last N lines from /data/voxwatch.log via the backend API,
 * with an optional level filter and an auto-refresh toggle.
 */
function ServiceLogsSection() {
  const [lineCount, setLineCount] = useState(50);
  const [levelFilter, setLevelFilter] = useState<LogLevel>('all');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const logsEndRef = useRef<HTMLDivElement | null>(null);

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['system-logs', lineCount, levelFilter],
    queryFn: () => getLogs(lineCount, levelFilter),
    // Manual control — disable background refetch; auto-refresh is done below.
    refetchInterval: autoRefresh ? 5_000 : false,
    staleTime: 0,
  });

  // Scroll to the bottom of the log view when new entries arrive.
  useEffect(() => {
    if (data && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [data]);

  const entries: LogEntry[] = data?.entries ?? [];

  return (
    <div className="space-y-3">
      {/* Controls row */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Line count */}
        <div className="flex items-center gap-2">
          <label
            htmlFor="log-lines"
            className="text-xs font-medium text-gray-700 dark:text-gray-300"
          >
            Lines
          </label>
          <select
            id="log-lines"
            value={lineCount}
            onChange={(e) => setLineCount(Number(e.target.value))}
            className={cn(
              'rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-xs',
              'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500',
              'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
            )}
          >
            {[25, 50, 100, 200, 500].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>

        {/* Level filter */}
        <div className="flex items-center gap-2">
          <label
            htmlFor="log-level"
            className="text-xs font-medium text-gray-700 dark:text-gray-300"
          >
            Level
          </label>
          <select
            id="log-level"
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value as LogLevel)}
            className={cn(
              'rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-xs',
              'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500',
              'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
            )}
          >
            {LOG_LEVELS.map((l) => (
              <option key={l} value={l}>{l === 'all' ? 'All levels' : l}</option>
            ))}
          </select>
        </div>

        {/* Auto-refresh toggle */}
        <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-700 dark:text-gray-300">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Auto-refresh (5s)
        </label>

        {/* Manual refresh */}
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className={cn(
            'ml-auto flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-600',
            'hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500',
            'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700',
            'disabled:opacity-50',
          )}
          aria-label="Refresh logs"
        >
          <RefreshCw
            className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')}
            aria-hidden="true"
          />
          Refresh
        </button>
      </div>

      {/* Log file path badge */}
      {data?.log_file && (
        <p className="font-mono text-[10px] text-gray-400 dark:text-gray-500">
          {data.log_file}
          {data.lines_read > 0 && (
            <span className="ml-2 text-gray-400">
              ({data.lines_read} lines read, {entries.length} shown)
            </span>
          )}
        </p>
      )}

      {/* Error banner when log file is missing */}
      {data?.error && (
        <div className="flex items-start gap-2 rounded-lg bg-yellow-50 px-3 py-2.5 text-xs text-yellow-700 dark:bg-yellow-950/30 dark:text-yellow-400">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          <span>
            {data.error}. The log file is created when VoxWatch starts and begins processing
            events.
          </span>
        </div>
      )}

      {/* Log viewer */}
      <div
        className="h-80 overflow-y-auto rounded-lg bg-gray-950 p-3 text-xs"
        role="log"
        aria-live="polite"
        aria-label="VoxWatch service logs"
      >
        {isLoading && (
          <div className="flex h-full items-center justify-center text-gray-500">
            <Loader className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
            Loading logs...
          </div>
        )}

        {isError && (
          <div className="flex h-full items-center justify-center text-red-400">
            <XCircle className="mr-2 h-4 w-4" aria-hidden="true" />
            Failed to load logs. Is the backend reachable?
          </div>
        )}

        {!isLoading && !isError && entries.length === 0 && (
          <div className="flex h-full items-center justify-center text-gray-500">
            No log entries found.
          </div>
        )}

        {entries.map((entry, idx) => (
          <div
            // Use index as key — log lines don't have stable IDs.
            // eslint-disable-next-line react/no-array-index-key
            key={idx}
            className="mb-1 flex gap-2 font-mono"
          >
            {/* Timestamp — full date + time */}
            <span className="flex-shrink-0 whitespace-nowrap text-gray-600">
              {entry.timestamp ?? ''}
            </span>

            {/* Level badge */}
            <span
              className={cn(
                'flex-shrink-0 rounded px-1 py-0.5 text-[10px] font-bold leading-none',
                levelBadgeClass(entry.level),
              )}
            >
              {entry.level === 'UNKNOWN' ? '···' : entry.level.slice(0, 4)}
            </span>

            {/* Logger name */}
            {entry.logger && (
              <span className="flex-shrink-0 text-gray-500">
                {entry.logger.split('.').pop()}
              </span>
            )}

            {/* Message */}
            <span className={cn('min-w-0 break-all', levelClass(entry.level))}>
              {entry.message || entry.raw}
            </span>
          </div>
        ))}

        {/* Scroll target */}
        <div ref={logsEndRef} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

/** Section identifiers for the open/closed state map. */
type SectionKey = 'audio' | 'tts' | 'compat' | 'mqtt' | 'logs';

/**
 * Tests page — unified diagnostics panel for VoxWatch operators.
 *
 * All five testing tools are presented as collapsible cards so the full page
 * fits on mobile without requiring horizontal scrolling. Each section is
 * independently toggleable — multiple sections can be open simultaneously.
 */
export function TestsPage() {
  // Track which sections are open. Audio push starts open as it is the most
  // commonly used tool; others start collapsed.
  const [open, setOpen] = useState<Record<SectionKey, boolean>>({
    audio: true,
    tts: false,
    compat: false,
    mqtt: false,
    logs: false,
  });

  const toggle = useCallback((key: SectionKey) => {
    setOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // Camera list from the status API
  const { status } = useServiceStatus();
  const cameras = status?.cameras ?? [];

  // TTS config — read engine and voice from the saved config
  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: getConfig,
    staleTime: 60_000,
  });
  const ttsEngine = config?.tts?.engine ?? '';
  // Pick the correct voice field based on the active engine
  const ttsVoice = (() => {
    const tts = config?.tts;
    if (!tts) return '';
    switch (ttsEngine) {
      case 'kokoro': return tts.kokoro_voice ?? 'af_heart';
      case 'piper': return tts.piper_model ?? 'en_US-lessac-medium';
      case 'elevenlabs': return tts.elevenlabs_voice_id ?? '';
      case 'openai': return tts.openai_voice ?? 'onyx';
      case 'cartesia': return tts.cartesia_voice_id ?? '';
      case 'polly': return tts.polly_voice_id ?? 'Matthew';
      case 'espeak': return 'espeak';
      default: return '';
    }
  })();

  return (
    <ErrorBoundary>
      <div className="space-y-4">
        {/* ── Section 1: Audio Push Test ─────────────────────────────────── */}
        <SectionCard
          icon={Volume2}
          title="Audio Push Test"
          description="Push test audio directly to a camera speaker via go2rtc."
          open={open.audio}
          onToggle={() => toggle('audio')}
        >
          <TestAudioButton />
        </SectionCard>

        {/* ── Section 2: TTS Voice Test ──────────────────────────────────── */}
        <SectionCard
          icon={Mic2}
          title="TTS Voice Test"
          description="Generate a browser-playable preview clip using the current TTS engine."
          open={open.tts}
          onToggle={() => toggle('tts')}
          headerExtra={
            ttsEngine ? (
              <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-700 dark:bg-blue-950/40 dark:text-blue-400">
                {ttsEngine}
              </span>
            ) : undefined
          }
        >
          <TtsVoiceTestSection ttsEngine={ttsEngine} ttsVoice={ttsVoice} />
        </SectionCard>

        {/* ── Section 3: Camera Compatibility Test ───────────────────────── */}
        <SectionCard
          icon={Camera}
          title="Camera Compatibility Test"
          description="Push a test tone to a specific camera and inspect backchannel codec info."
          open={open.compat}
          onToggle={() => toggle('compat')}
        >
          <CameraCompatibilitySection
            cameras={cameras}
            frigateVersion={status?.frigate.version}
            go2rtcVersion={status?.go2rtc.version}
          />
        </SectionCard>

        {/* ── Section 4: MQTT Simulation ─────────────────────────────────── */}
        <SectionCard
          icon={Terminal}
          title="MQTT Simulation"
          description="Test the full detection pipeline without a real person using the CLI script."
          open={open.mqtt}
          onToggle={() => toggle('mqtt')}
        >
          <MqttSimulationSection cameras={cameras} />
        </SectionCard>

        {/* ── Section 5: Service Logs ────────────────────────────────────── */}
        <SectionCard
          icon={FileText}
          title="Service Logs"
          description="Tail the VoxWatch service log for ERROR, WARNING, and DEBUG output."
          open={open.logs}
          onToggle={() => toggle('logs')}
        >
          <ServiceLogsSection />
        </SectionCard>
      </div>
    </ErrorBoundary>
  );
}
