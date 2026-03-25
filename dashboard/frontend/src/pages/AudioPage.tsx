/**
 * AudioPage — manual test audio push panel.
 *
 * Provides a simple UI to push a test audio stream to a camera speaker via
 * go2rtc, confirming that the audio path is configured correctly.
 */

import { TestAudioButton } from '@/components/audio/TestAudioButton';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';

/**
 * Audio management page — test audio push only.
 */
export function AudioPage() {
  return (
    <div className="space-y-5">
      <ErrorBoundary>
        <TestAudioButton />
      </ErrorBoundary>
    </div>
  );
}
