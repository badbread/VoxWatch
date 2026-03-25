/**
 * TestAudioButton — mobile-friendly audio test push panel.
 *
 * Big tap targets, clear visual feedback, quick-action camera buttons
 * so you can test audio from a phone while standing at the camera.
 *
 * The camera list is sourced from the status API (via useServiceStatus),
 * which returns ALL cameras visible across Frigate, go2rtc, and the VoxWatch
 * config — not just VoxWatch-enrolled cameras. This lets you test audio on
 * any camera go2rtc can reach, regardless of whether it has been configured
 * in VoxWatch yet.
 *
 * VoxWatch-configured cameras render with a blue button.
 * Unconfigured cameras render with a gray button and a "(not configured)"
 * subtitle to indicate they haven't been enrolled in VoxWatch, but are
 * still clickable for a raw audio-pipeline test.
 */

import { useState } from 'react';
import { Play, Loader, CheckCircle, XCircle, Volume2 } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { testAudio } from '@/api/audio';
import { useServiceStatus } from '@/hooks/useServiceStatus';

/**
 * Mobile-friendly audio push test with big tap targets.
 *
 * Camera list is derived from the aggregated status endpoint so every camera
 * visible in Frigate or go2rtc appears — even cameras not yet in VoxWatch
 * config. Unconfigured cameras get a "(not configured)" label but are still
 * clickable for connectivity testing.
 */
export function TestAudioButton() {
  // useServiceStatus polls /api/status every 15 s and returns all cameras
  // from the merged Frigate + go2rtc + VoxWatch config list.
  const { status } = useServiceStatus();
  const allCameras = status?.cameras ?? [];

  const [selectedCamera, setSelectedCamera] = useState('');
  const [message, setMessage] = useState('');
  const [showMessage, setShowMessage] = useState(false);

  const mutation = useMutation({
    mutationFn: testAudio,
  });

  /**
   * Fire a test audio push for the given camera name (or the currently
   * selected camera if no name is passed).
   *
   * @param cameraName - Camera to push to; falls back to selectedCamera.
   */
  const handleTest = (cameraName?: string) => {
    const cam = cameraName ?? selectedCamera;
    if (!cam) return;
    setSelectedCamera(cam);
    const trimmed = message.trim();
    mutation.mutate({
      camera_name: cam,
      ...(trimmed ? { message: trimmed } : {}),
    });
  };

  return (
    <div className="space-y-4">
      {/* Quick-fire camera buttons — big tap targets for mobile */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700/50 dark:bg-gray-900">
        <h3 className="mb-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
          Quick Test
        </h3>
        <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">
          Tap a camera to push the default test audio immediately.
          Gray cameras are visible in go2rtc but not yet configured in VoxWatch.
        </p>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {allCameras.map((cam) => {
            const isPending = mutation.isPending && selectedCamera === cam.name;
            const isSuccess =
              mutation.isSuccess &&
              selectedCamera === cam.name &&
              mutation.data?.success;

            // Configured cameras: blue styling.
            // Unconfigured cameras: gray styling to signal they are not yet
            // enrolled in VoxWatch, but still clickable for testing.
            const idleStyle = cam.enabled
              ? 'border-gray-200 bg-gray-50 text-gray-800 hover:border-blue-300 hover:bg-blue-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:border-blue-600 dark:hover:bg-blue-950/20'
              : 'border-gray-200 bg-gray-50 text-gray-500 hover:border-gray-400 hover:bg-gray-100 dark:border-gray-700/50 dark:bg-gray-800/50 dark:text-gray-500 dark:hover:border-gray-600';

            return (
              <button
                key={cam.name}
                onClick={() => handleTest(cam.name)}
                disabled={isPending}
                className={cn(
                  'flex flex-col items-center justify-center gap-1 rounded-xl border-2 px-3 py-3 text-sm font-semibold transition-all',
                  'active:scale-95',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500',
                  isPending
                    ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-300'
                    : isSuccess
                      ? 'border-green-500 bg-green-50 text-green-700 dark:bg-green-950/30 dark:text-green-300'
                      : idleStyle,
                )}
              >
                {/* Icon row */}
                <span className="flex items-center gap-1.5">
                  {isPending ? (
                    <Loader className="h-4 w-4 animate-spin" />
                  ) : isSuccess ? (
                    <CheckCircle className="h-4 w-4" />
                  ) : (
                    <Volume2 className="h-4 w-4" />
                  )}
                  {cam.name}
                </span>

                {/* "(not configured)" subtitle for unconfigured cameras */}
                {!cam.enabled && (
                  <span className="text-xs font-normal opacity-60">
                    not configured
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Custom message section */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700/50 dark:bg-gray-900">
        <button
          onClick={() => setShowMessage(!showMessage)}
          className="flex w-full items-center justify-between text-sm font-semibold text-gray-900 dark:text-gray-100"
        >
          Custom Message
          <span className="text-xs font-normal text-blue-500">
            {showMessage ? 'Hide' : 'Show'}
          </span>
        </button>

        {showMessage && (
          <div className="mt-3 space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300">
                Camera
              </label>
              <select
                value={selectedCamera}
                onChange={(e) => setSelectedCamera(e.target.value)}
                className={cn(
                  'w-full rounded-lg border border-gray-300 bg-white px-3 py-3 text-base',
                  'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500',
                  'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                )}
              >
                <option value="">Select camera...</option>
                {/* Group configured and unconfigured cameras with optgroup labels */}
                {allCameras.some((c) => c.enabled) && (
                  <optgroup label="VoxWatch Configured">
                    {allCameras
                      .filter((c) => c.enabled)
                      .map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                  </optgroup>
                )}
                {allCameras.some((c) => !c.enabled) && (
                  <optgroup label="Not Configured (test only)">
                    {allCameras
                      .filter((c) => !c.enabled)
                      .map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                  </optgroup>
                )}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300">
                Message
              </label>
              <textarea
                rows={3}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Type a custom message to speak through the camera..."
                className={cn(
                  'w-full rounded-lg border border-gray-300 bg-white px-3 py-3 text-base resize-none',
                  'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500',
                  'dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100',
                )}
              />
            </div>

            <button
              onClick={() => handleTest()}
              disabled={!selectedCamera || mutation.isPending}
              className={cn(
                'flex w-full items-center justify-center gap-2 rounded-xl px-4 py-4 text-base font-semibold text-white',
                'active:scale-[0.98] transition-transform',
                'focus:outline-none focus:ring-2 focus:ring-blue-500',
                'disabled:cursor-not-allowed disabled:opacity-50',
                'bg-blue-600 hover:bg-blue-700',
              )}
            >
              {mutation.isPending ? (
                <Loader className="h-5 w-5 animate-spin" />
            ) : (
                <Play className="h-5 w-5" />
              )}
              {mutation.isPending ? 'Sending...' : 'Send Custom Message'}
            </button>
          </div>
        )}
      </div>

      {/* Result feedback */}
      {mutation.isSuccess && mutation.data && (
        <div
          className={cn(
            'flex items-start gap-3 rounded-xl p-4 text-sm',
            mutation.data.success
              ? 'bg-green-50 text-green-800 dark:bg-green-950/20 dark:text-green-300'
              : 'bg-red-50 text-red-800 dark:bg-red-950/20 dark:text-red-300',
          )}
        >
          {mutation.data.success ? (
            <CheckCircle className="mt-0.5 h-5 w-5 flex-shrink-0" />
          ) : (
            <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0" />
          )}
          <div>
            <p className="font-semibold">
              {mutation.data.success ? 'Audio sent' : 'Push failed'}
            </p>
            <p className="mt-0.5 text-xs opacity-80">
              {mutation.data.message}
            </p>
          </div>
        </div>
      )}

      {mutation.isError && (
        <div className="flex items-start gap-3 rounded-xl bg-red-50 p-4 text-sm text-red-800 dark:bg-red-950/20 dark:text-red-300">
          <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0" />
          <p className="font-semibold">Failed to contact backend.</p>
        </div>
      )}
    </div>
  );
}
