/**
 * SetupPage — full-screen first-run setup wizard host.
 *
 * This page is intentionally rendered OUTSIDE the AppShell so there is
 * no sidebar, header, or navigation chrome. The user sees a clean,
 * focused dark-gradient screen with the VoxWatch logo and the wizard
 * card centred at max-w-3xl.
 *
 * The page is only reachable when config.yaml does not exist (enforced by
 * SetupGuard in App.tsx). Once the wizard completes and config.yaml is
 * written, the wizard navigates to '/' and SetupGuard stops redirecting.
 */

import { Shield } from 'lucide-react';
import { SetupWizard } from '@/components/setup/SetupWizard';

/**
 * Full-screen setup wizard page — no AppShell, no sidebar.
 *
 * @example
 *   // Registered in App.tsx:
 *   <Route path="/setup" element={<SetupPage />} />
 */
export function SetupPage() {
  return (
    <div
      className="min-h-screen w-full bg-gray-950"
      style={{
        background: 'radial-gradient(ellipse at 50% 0%, rgba(30, 58, 138, 0.25) 0%, transparent 60%), #030712',
      }}
    >
      {/* Centered content column */}
      <div className="mx-auto max-w-3xl px-4 py-8 sm:py-12">

        {/* Top wordmark — shown on all steps */}
        <div className="mb-8 flex items-center justify-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-blue-600/30">
            <Shield className="h-4.5 w-4.5 text-blue-400" />
          </div>
          <span className="text-sm font-bold tracking-widest text-gray-500 uppercase">
            VoxWatch
          </span>
        </div>

        {/* Wizard card */}
        <div className="rounded-2xl border border-gray-800/60 bg-gray-900/80 shadow-2xl backdrop-blur-sm">
          <SetupWizard />
        </div>

        {/* Footer */}
        <p className="mt-6 text-center text-xs text-gray-700">
          VoxWatch — open-source AI security audio deterrent.
        </p>
      </div>
    </div>
  );
}
