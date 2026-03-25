/**
 * Sidebar — fixed left navigation with logo, nav links, status dot, and dark
 * mode toggle.
 *
 * Width: 256px on desktop. On tablet it collapses to icon-only (64px). On
 * mobile it's hidden in favour of the MobileNav bottom tab bar.
 */

import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Settings,
  Volume2,
  Wand2,
  Sun,
  Moon,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { useServiceStatus } from '@/hooks/useServiceStatus';
import { useDarkMode } from '@/hooks/useDarkMode';


interface NavItem {
  label: string;
  to: string;
  icon: React.ElementType;
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard },
  { label: 'Setup Wizard', to: '/wizard', icon: Wand2 },
  { label: 'Configuration', to: '/config', icon: Settings },
  { label: 'Audio Test', to: '/audio', icon: Volume2 },
];

export interface SidebarProps {
  /** Whether the sidebar is in collapsed (icon-only) mode. */
  collapsed?: boolean;
}

/**
 * Application sidebar navigation.
 *
 * Reads service status to render the bottom health indicator dot.
 */
export function Sidebar({ collapsed = false }: SidebarProps) {
  const { status, isLoading } = useServiceStatus();
  const { isDark, toggle } = useDarkMode();

  // Derive health dot colour: green when both Frigate and go2rtc are reachable,
  // yellow while loading, red when at least one service is unreachable.
  const frigateOk = status?.frigate?.reachable ?? false;
  const go2rtcOk = status?.go2rtc?.reachable ?? false;
  const servicesOk = frigateOk && go2rtcOk;
  const dotColor = isLoading
    ? 'bg-yellow-500'
    : servicesOk
      ? 'bg-green-500'
      : 'bg-red-500';
  const dotLabel = isLoading
    ? 'Loading'
    : servicesOk
      ? 'Connected'
      : 'Degraded';

  return (
    <aside
      className={cn(
        'flex h-full flex-col border-r border-gray-200 bg-gray-50 dark:border-gray-700/50 dark:bg-gray-900',
        'transition-[width] duration-200',
        collapsed ? 'w-16' : 'w-64',
      )}
    >
      {/* Logo */}
      <div
        className={cn(
          'flex items-center border-b border-gray-200 dark:border-gray-700/50',
          collapsed ? 'h-14 justify-center px-2' : 'h-14 px-3',
        )}
      >
        {collapsed ? (
          <img
            src={isDark ? '/branding/icon-dark.svg' : '/branding/icon-light.svg'}
            alt="VoxWatch"
            className="h-8 w-8"
          />
        ) : (
          <img
            src={isDark ? '/branding/logo-dark-transparent.svg' : '/branding/logo-light-transparent.svg'}
            alt="VoxWatch"
            className="w-full max-w-[220px]"
          />
        )}
      </div>

      {/* Navigation links */}
      <nav className="flex-1 overflow-y-auto py-4" aria-label="Main navigation">
        <ul className="space-y-0.5 px-2">
          {NAV_ITEMS.map(({ label, to, icon: Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
                    isActive
                      ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-400'
                      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100',
                    collapsed && 'justify-center px-0',
                  )
                }
                title={collapsed ? label : undefined}
              >
                <Icon className="h-4.5 w-4.5 flex-shrink-0" aria-hidden="true" />
                {!collapsed && <span>{label}</span>}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Footer: status dot + dark mode toggle */}
      <div
        className={cn(
          'border-t border-gray-200 py-3 dark:border-gray-700/50',
          collapsed ? 'flex flex-col items-center gap-3 px-0' : 'px-4',
        )}
      >
        {/* Service status indicator */}
        <div
          className={cn(
            'flex items-center gap-2.5',
            collapsed ? 'justify-center' : '',
          )}
          title={`VoxWatch: ${dotLabel}`}
        >
          <span className="relative flex h-3 w-3 flex-shrink-0">
            <span
              className={cn(
                'absolute inline-flex h-full w-full animate-ping rounded-full opacity-60',
                dotColor,
              )}
            />
            <span
              className={cn(
                'relative inline-flex h-3 w-3 rounded-full',
                dotColor,
              )}
            />
          </span>
          {!collapsed && (
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {dotLabel}
            </span>
          )}
        </div>

        {/* Dark mode toggle */}
        <button
          onClick={toggle}
          aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          className={cn(
            'mt-2 flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-xs text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200',
            collapsed ? 'justify-center' : '',
          )}
        >
          {isDark ? (
            <Sun className="h-4 w-4 flex-shrink-0" />
          ) : (
            <Moon className="h-4 w-4 flex-shrink-0" />
          )}
          {!collapsed && (
            <span>{isDark ? 'Light mode' : 'Dark mode'}</span>
          )}
        </button>
      </div>
    </aside>
  );
}
