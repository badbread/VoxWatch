/**
 * Header — top bar with page title and optional action slot.
 *
 * The bell notification button is kept as a placeholder for future
 * notification features.
 */

// Bell notification removed — no alerts system yet

export interface HeaderProps {
  /** Page title displayed in the header. */
  title: string;
  /** Optional subtitle / breadcrumb. */
  subtitle?: string | undefined;
  /** Optional action slot rendered on the right side. */
  actions?: React.ReactNode | undefined;
  /** Callback for the mobile hamburger menu button. */
  onMenuToggle?: (() => void) | undefined;
}

/**
 * Application top header bar.
 */
export function Header({ title, subtitle, actions, onMenuToggle }: HeaderProps) {
  return (
    <header className="flex h-16 flex-shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4 dark:border-gray-700/50 dark:bg-gray-950 sm:px-6">
      {/* Left: hamburger (mobile) + page title */}
      <div className="flex min-w-0 items-center gap-3">
        {onMenuToggle && (
          <button
            onClick={onMenuToggle}
            aria-label="Toggle menu"
            className="flex-shrink-0 rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200 lg:hidden"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M4 6h16M4 12h16M4 18h16"
              />
            </svg>
          </button>
        )}
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold text-gray-900 dark:text-gray-100">
            {title}
          </h1>
          {subtitle && (
            <p className="truncate text-xs text-gray-500 dark:text-gray-400">
              {subtitle}
            </p>
          )}
        </div>
      </div>

      {/* Right: actions */}
      {actions && (
        <div className="flex flex-shrink-0 items-center gap-4">
          {actions}
        </div>
      )}
    </header>
  );
}
