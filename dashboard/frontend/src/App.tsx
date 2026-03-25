/**
 * App — root application component.
 *
 * Sets up:
 * - React Router DOM browser router with all page routes
 * - React Query client with sensible defaults
 * - Zustand-backed toast notification stack
 *
 * The QueryClient is configured to retry failed requests twice and treat
 * data as stale after 30 seconds (individual queries can override staleTime).
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { ToastContainer } from '@/components/common/ToastContainer';
import { DashboardPage } from '@/pages/DashboardPage';
import { ConfigPage } from '@/pages/ConfigPage';
import { CamerasPage } from '@/pages/CamerasPage';
import { TestsPage } from '@/pages/TestsPage';
import { WizardPage } from '@/pages/WizardPage';
import { NotFoundPage } from '@/pages/NotFoundPage';

/** Shared React Query client instance. */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 15_000),
      staleTime: 30_000,
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: 0,
    },
  },
});

/**
 * Root application with routing, query, and toast infrastructure.
 */
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* All main pages share the AppShell layout */}
          <Route element={<AppShell />}>
            <Route index element={<DashboardPage />} />
            <Route path="/cameras" element={<CamerasPage />} />
            <Route path="/config" element={<ConfigPage />} />
            <Route path="/tests" element={<TestsPage />} />
            <Route path="/wizard" element={<WizardPage />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </BrowserRouter>
      {/* Global toast stack — renders outside the router tree */}
      <ToastContainer />
    </QueryClientProvider>
  );
}
