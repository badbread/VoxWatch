/**
 * WizardPage — page wrapper for the Camera Setup Wizard.
 *
 * Accessible at /wizard. Accepts an optional `camera` query param that the
 * CameraSetupWizard reads to pre-select a specific camera at load time.
 *
 * Layout: centred, max-width constrained to keep the multi-step wizard form
 * readable without sprawling across ultra-wide viewports.
 */

import { CameraSetupWizard } from '@/components/wizard/CameraSetupWizard';

/**
 * Slim page shell that centres the CameraSetupWizard within the AppShell
 * content area.
 */
export function WizardPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <CameraSetupWizard />
    </div>
  );
}
