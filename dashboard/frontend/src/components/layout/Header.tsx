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
  /** Callback for the mobile hamburger / close menu button. */
  onMenuToggle?: (() => void) | undefined;
  /**
   * Whether the mobile slide-in drawer is currently open.
   * When true the button renders an X (close) icon instead of the hamburger.
   */
  mobileDrawerOpen?: boolean | undefined;
}

/**
 * Application top header bar.
 *
 * Touch target note: the hamburger button uses min-w-[44px] min-h-[44px] to
 * meet the WCAG 2.5.5 / Apple HIG 44pt minimum for reliable touch activation
 * on Android and iOS. The visible icon remains 20px; the extra tap area is
 * provided by padding and the explicit minimum dimensions.
 */
export function Header({ title, subtitle, actions, onMenuToggle, mobileDrawerOpen = false }: HeaderProps) {
  return (
    <header className="flex h-16 flex-shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4 dark:border-gray-700/50 dark:bg-gray-950 sm:px-6">
      {/* Left: hamburger (mobile) + page title */}
      <div className="flex min-w-0 items-center gap-3">
        {onMenuToggle && (
          <button
            type="button"
            onClick={onMenuToggle}
            aria-label={mobileDrawerOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={mobileDrawerOpen}
            aria-controls="mobile-sidebar"
            className="flex min-h-[44px] min-w-[44px] flex-shrink-0 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200 md:hidden"
          >
            {mobileDrawerOpen ? (
              /* Close (X) icon — shown when the drawer is open */
              <svg
                className="h-5 w-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
                aria-hidden="true"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              /* Hamburger icon */
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
            )}
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
