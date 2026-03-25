/**
 * SupportCard — dismissible "Support VoxWatch" call-to-action card.
 *
 * Shown at the bottom of the Dashboard page. Once dismissed, the card stays
 * hidden by writing a flag to localStorage so the preference survives page
 * reloads. The card is non-intrusive — it uses gentle language and a heart
 * icon rather than upgrade or paywall framing.
 *
 * Design principle: "Show value before asking. Never block core usage."
 *
 * localStorage key: "voxwatch_support_dismissed"
 */

import { useState, useEffect } from 'react';
import { Heart, X, ExternalLink } from 'lucide-react';
import { cn } from '@/utils/cn';

/** localStorage key used to persist the dismissal state across sessions. */
const DISMISSED_KEY = 'voxwatch_support_dismissed';

/** Buy Me a Coffee support URL. */
const SUPPORT_URL = 'https://buymeacoffee.com/badbread';

/**
 * Reads the dismissal flag from localStorage.
 * Returns false if localStorage is unavailable (e.g. SSR or private browsing).
 */
function getIsDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY) === 'true';
  } catch {
    return false;
  }
}

/**
 * Persists the dismissal flag to localStorage.
 * Silently ignores errors (quota exceeded, private mode restrictions, etc.).
 */
function setIsDismissed(dismissed: boolean): void {
  try {
    if (dismissed) {
      localStorage.setItem(DISMISSED_KEY, 'true');
    } else {
      localStorage.removeItem(DISMISSED_KEY);
    }
  } catch {
    // Ignore storage errors — the card will just reappear on next load.
  }
}

/**
 * Dismissible support card rendered at the bottom of the Dashboard.
 *
 * When dismissed the component returns null immediately and writes to
 * localStorage so the card does not reappear on subsequent loads.
 */
export function SupportCard() {
  const [visible, setVisible] = useState<boolean>(() => !getIsDismissed());

  // Keep localStorage in sync if state changes after mount
  // (handles edge case where flag changes in another tab).
  useEffect(() => {
    if (!visible) {
      setIsDismissed(true);
    }
  }, [visible]);

  if (!visible) return null;

  return (
    <div
      role="complementary"
      aria-label="Support VoxWatch"
      className={cn(
        'relative rounded-xl border px-5 py-4',
        'border-amber-200 bg-amber-50/60',
        'dark:border-amber-800/40 dark:bg-amber-950/10',
      )}
    >
      {/* Dismiss button */}
      <button
        type="button"
        aria-label="Dismiss support card"
        onClick={() => setVisible(false)}
        className={cn(
          'absolute right-3 top-3 rounded-lg p-1',
          'text-amber-400 hover:bg-amber-100 hover:text-amber-600',
          'dark:text-amber-600 dark:hover:bg-amber-900/30 dark:hover:text-amber-400',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400',
          'transition-colors',
        )}
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>

      <div className="flex items-start gap-3 pr-6">
        {/* Heart icon */}
        <div
          className={cn(
            'mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full',
            'bg-amber-100 dark:bg-amber-900/40',
          )}
          aria-hidden="true"
        >
          <Heart className="h-4 w-4 text-amber-600 dark:text-amber-400" />
        </div>

        <div className="min-w-0 flex-1">
          {/* Title */}
          <p className="text-sm font-semibold text-amber-900 dark:text-amber-200">
            Support VoxWatch
          </p>

          {/* Body */}
          <p className="mt-0.5 text-sm text-amber-700 dark:text-amber-400">
            If this made your setup more powerful (or just more fun), consider supporting
            development.
          </p>

          {/* CTA buttons */}
          <div className="mt-3 flex flex-wrap gap-2">
            <a
              href={SUPPORT_URL}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium',
                'bg-amber-500 text-white hover:bg-amber-600',
                'dark:bg-amber-600 dark:hover:bg-amber-500',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400',
                'transition-colors',
              )}
            >
              <Heart className="h-3 w-3" aria-hidden="true" />
              One-time Support
              <ExternalLink className="h-3 w-3 opacity-70" aria-hidden="true" />
            </a>

            <a
              href={SUPPORT_URL}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium',
                'border-amber-400 text-amber-700 hover:bg-amber-100',
                'dark:border-amber-700/60 dark:text-amber-400 dark:hover:bg-amber-900/20',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400',
                'transition-colors',
              )}
            >
              Become a Supporter
              <ExternalLink className="h-3 w-3 opacity-70" aria-hidden="true" />
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
