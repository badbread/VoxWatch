/**
 * AppShell — root layout component that composes sidebar, header, and content.
 *
 * Responsive breakpoints:
 * - Mobile (<768px):   no sidebar, bottom tab bar, full-width content
 * - Tablet (768–1023): collapsed (icon-only) sidebar + content
 * - Desktop (1024+):   full sidebar + content
 *
 * The sidebar collapse state is stored in local component state and toggled by
 * the hamburger button in the Header.
 */

import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { MobileNav } from './MobileNav';

/** Maps route paths to human-readable page titles for the header. */
const PAGE_TITLES: Record<string, { title: string; subtitle?: string }> = {
  '/': { title: 'Dashboard', subtitle: 'Real-time monitoring overview' },
  '/cameras': { title: 'Cameras', subtitle: 'Camera health and snapshots' },
  '/config': {
    title: 'Configuration',
    subtitle: 'Edit and save VoxWatch settings',
  },
  '/audio': {
    title: 'Audio Test',
    subtitle: 'Push test audio to camera speakers',
  },
  '/wizard': {
    title: 'Camera Setup',
    subtitle: 'Test and configure camera audio',
  },
};

/**
 * Root application shell with responsive sidebar layout.
 *
 * Uses React Router <Outlet /> to render the active page inside the main
 * content area so the sidebar and header remain mounted across navigation.
 */
export function AppShell() {
  // Tablet: collapse the sidebar to icon-only mode
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const location = useLocation();
  const pageInfo = PAGE_TITLES[location.pathname] ?? {
    title: 'VoxWatch',
  };

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-gray-950">
      {/* Sidebar — hidden on mobile, icon-only or full on md+ */}
      <div className="hidden md:flex md:flex-shrink-0">
        <Sidebar collapsed={sidebarCollapsed} />
      </div>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Header
          title={pageInfo.title}
          subtitle={pageInfo.subtitle}
          onMenuToggle={() => setSidebarCollapsed((c) => !c)}
        />

        {/* Scrollable page content area */}
        <main
          id="main-content"
          className="flex-1 overflow-y-auto px-4 py-6 pb-20 sm:px-6 md:pb-6 lg:px-8"
        >
          <Outlet />
        </main>
      </div>

      {/* Mobile bottom nav */}
      <MobileNav />
    </div>
  );
}
