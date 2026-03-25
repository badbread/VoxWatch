/**
 * WelcomeStep — first screen of the first-run setup wizard.
 *
 * Presents the VoxWatch brand and a brief value proposition before
 * the user commits to the guided setup flow. The single action is
 * "Get Started" which advances to the Frigate connection step.
 *
 * Design intent: cinematic, dark, minimal. No form fields here — just
 * brand presence and a clear call to action.
 */

import { Shield, ArrowRight } from 'lucide-react';
import { cn } from '@/utils/cn';

/** Props for WelcomeStep. */
interface WelcomeStepProps {
  /** Called when the user clicks "Get Started". */
  onNext: () => void;
}

/**
 * Full-card welcome screen with logo, tagline, and start button.
 *
 * @example
 *   <WelcomeStep onNext={() => dispatch({ type: 'SET_STEP', step: 'frigate' })} />
 */
export function WelcomeStep({ onNext }: WelcomeStepProps) {
  return (
    <div className="flex flex-col items-center gap-8 px-6 py-12 text-center">
      {/* Brand mark */}
      <div className="relative">
        {/* Outer glow ring */}
        <div className="absolute inset-0 rounded-full bg-blue-500/20 blur-xl" aria-hidden="true" />
        <div
          className={cn(
            'relative flex h-24 w-24 items-center justify-center rounded-3xl',
            'bg-gradient-to-br from-blue-600 to-blue-800',
            'shadow-[0_0_40px_rgba(59,130,246,0.4)]',
          )}
        >
          <Shield className="h-12 w-12 text-white" />
        </div>
      </div>

      {/* Heading block */}
      <div className="space-y-3">
        <h1 className="text-4xl font-bold tracking-tight text-gray-100">
          Welcome to VoxWatch
        </h1>
        <p className="mx-auto max-w-sm text-lg text-gray-400">
          AI-powered audio deterrent for Frigate.
          Get set up in 2 minutes.
        </p>
      </div>

      {/* Feature bullets */}
      <ul className="space-y-2 text-sm text-gray-500">
        {[
          'Connects to your Frigate NVR automatically',
          'Speaks through camera speakers when people are detected',
          'Powered by real AI — no canned messages',
        ].map((item) => (
          <li key={item} className="flex items-center gap-2 justify-center">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-500 shrink-0" aria-hidden="true" />
            {item}
          </li>
        ))}
      </ul>

      {/* Primary action */}
      <button
        onClick={onNext}
        className={cn(
          'flex items-center gap-3 rounded-2xl px-8 py-4',
          'bg-blue-600 hover:bg-blue-500 active:bg-blue-700',
          'text-lg font-semibold text-white',
          'transition-all duration-150 active:scale-[0.98]',
          'shadow-[0_0_20px_rgba(59,130,246,0.3)] hover:shadow-[0_0_30px_rgba(59,130,246,0.5)]',
          'focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 focus:ring-offset-gray-900',
        )}
      >
        Get Started
        <ArrowRight className="h-5 w-5" />
      </button>

      <p className="text-xs text-gray-600">
        No account required. All data stays on your server.
      </p>
    </div>
  );
}
