/**
 * SupportCard — minimal single-line footer with a buymeacoffee link.
 *
 * Replaces the old dismissible card with a subtle footer that stays out of
 * the way while still surfacing the support link for users who want it.
 */

/** Buy Me a Coffee support URL. */
const SUPPORT_URL = 'https://buymeacoffee.com/badbread';

/**
 * Subtle one-line footer rendered at the bottom of the Dashboard.
 */
export function SupportCard() {
  return (
    <div className="flex items-center justify-center gap-2 py-3 text-xs text-gray-500 dark:text-gray-600">
      <span>If VoxWatch made your setup smarter</span>
      <a
        href={SUPPORT_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-amber-600 hover:text-amber-500 dark:text-amber-500 dark:hover:text-amber-400"
      >
        buy me a coffee ☕
      </a>
    </div>
  );
}
