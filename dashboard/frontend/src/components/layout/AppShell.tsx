/**
 * AppShell — root layout component that composes sidebar, header, and content.
 *
 * Responsive breakpoints:
 * - Mobile (<768px):   no sidebar, bottom tab bar, full-width content
 * - Tablet (768–1023): collapsed (icon-only) sidebar + content
 * - Desktop (1024+):   full sidebar + content
 *
 * The sidebar collapse state is stored in local component state and toggled by
 * the hamburger button in the Header. On mobile, a separate mobileDrawerOpen
 * boolean drives a slide-in overlay drawer so the hamburger actually produces
 * visible navigation on small screens where the sidebar is CSS-hidden.
 */

import { useState, useCallback } from 'react';
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
  '/tests': {
    title: 'Tests',
    subtitle: 'Audio push, TTS preview, camera compatibility, and service logs',
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
  // Tablet/desktop: collapse the sidebar to icon-only mode
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // Mobile: drawer overlay that slides in from the left when the hamburger is tapped
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  const location = useLocation();
  const pageInfo = PAGE_TITLES[location.pathname] ?? {
    title: 'VoxWatch',
  };

  /**
   * On mobile: toggle the slide-in drawer.
   * On tablet/desktop: toggle the icon-only sidebar collapse.
   * We can't detect breakpoints in JS without a hook, so we use both booleans
   * and let CSS control which UI is actually visible.
   */
  const handleMenuToggle = useCallback(() => {
    setMobileDrawerOpen((open) => !open);
    setSidebarCollapsed((c) => !c);
  }, []);

  const closeMobileDrawer = useCallback(() => setMobileDrawerOpen(false), []);

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-gray-950">
      {/* Mobile drawer backdrop — shown only on mobile when drawer is open */}
      {mobileDrawerOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          aria-hidden="true"
          onClick={closeMobileDrawer}
        />
      )}

      {/*
       * Mobile slide-in drawer — rendered as its own fixed panel on mobile.
       * On md+ the panel is never shown; the normal sidebar below takes over.
       */}
      <div
        id="mobile-sidebar"
        className={[
          'fixed inset-y-0 left-0 z-50 flex w-64 flex-shrink-0 flex-col transition-transform duration-300 ease-in-out md:hidden',
          mobileDrawerOpen ? 'translate-x-0' : '-translate-x-full',
        ].join(' ')}
        aria-label="Mobile sidebar"
      >
        <Sidebar collapsed={false} onNavClick={closeMobileDrawer} />
      </div>

      {/* Sidebar — hidden on mobile (drawer handles it), icon-only or full on md+ */}
      <div className="hidden md:flex md:flex-shrink-0">
        <Sidebar collapsed={sidebarCollapsed} />
      </div>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Header
          title={pageInfo.title}
          subtitle={pageInfo.subtitle}
          mobileDrawerOpen={mobileDrawerOpen}
          onMenuToggle={handleMenuToggle}
        />

        {/*
         * Scrollable page content area.
         * pb-20 on mobile reserves space above the fixed MobileNav (h-14 ≈ 56px).
         * md:pb-6 restores normal padding when the bottom nav is hidden.
         */}
        <main
          id="main-content"
          className="flex-1 overflow-y-auto px-4 py-6 pb-24 sm:px-6 md:pb-20 lg:px-8"
        >
          <Outlet />
        </main>
      </div>

      {/* Mobile bottom nav */}
      <MobileNav />
    </div>
  );
}
