/**
 * MobileNav — bottom tab bar shown on mobile (<768px).
 *
 * Provides the four primary navigation destinations as a compact icon + label
 * tab strip fixed to the bottom of the viewport. The Setup Wizard is accessible
 * via the sidebar on tablet/desktop or from the Dashboard page on mobile.
 * Hidden on tablet and desktop where the sidebar is visible.
 */

import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Camera,
  Settings,
  FlaskConical,
} from 'lucide-react';
import { cn } from '@/utils/cn';

interface TabItem {
  label: string;
  to: string;
  icon: React.ElementType;
}

/**
 * The four primary tab destinations shown on mobile.
 * Setup Wizard is omitted here — it is available from the Dashboard quick-links
 * or via the sidebar on tablet+ screens.
 */
const TABS: TabItem[] = [
  { label: 'Dashboard', to: '/',        icon: LayoutDashboard },
  { label: 'Cameras',   to: '/cameras', icon: Camera },
  { label: 'Config',    to: '/config',  icon: Settings },
  { label: 'Tests',     to: '/tests',   icon: FlaskConical },
];

/**
 * Mobile bottom navigation tab bar.
 *
 * Should be rendered inside the app shell and hidden via `md:hidden`.
 */
export function MobileNav() {
  return (
    <nav
      aria-label="Mobile navigation"
      className="fixed bottom-0 left-0 right-0 z-40 flex border-t border-gray-200 bg-white dark:border-gray-700/50 dark:bg-gray-900 md:hidden"
    >
      {TABS.map(({ label, to, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          className={({ isActive }) =>
            cn(
              'flex flex-1 flex-col items-center justify-center gap-0.5 py-2.5 text-xs font-medium transition-colors',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500',
              isActive
                ? 'text-blue-600 dark:text-blue-400'
                : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200',
            )
          }
        >
          <Icon className="h-5 w-5" aria-hidden="true" />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
