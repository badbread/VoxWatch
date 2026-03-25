/**
 * useDarkMode — dark mode toggle with localStorage persistence.
 *
 * Reads the user's stored preference on first load, falling back to the OS
 * `prefers-color-scheme` media query. The `dark` class is applied to
 * `document.documentElement` so Tailwind's `darkMode: 'class'` strategy works.
 */

import { useEffect, useState } from 'react';

const STORAGE_KEY = 'voxwatch-dark-mode';

/** Returns the system preference as a boolean. */
function systemPrefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

/** Reads the persisted preference; falls back to system preference. */
function getInitialDark(): boolean {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'true') return true;
    if (stored === 'false') return false;
  } catch {
    // localStorage unavailable (e.g. sandboxed iframe)
  }
  return systemPrefersDark();
}

/** Applies or removes the `dark` class on <html>. */
function applyDark(isDark: boolean): void {
  if (isDark) {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
}

export interface UseDarkModeReturn {
  /** Whether dark mode is currently active. */
  isDark: boolean;
  /** Toggle dark mode on/off. */
  toggle: () => void;
  /** Explicitly set dark mode. */
  setDark: (value: boolean) => void;
}

/**
 * Hook for reading and toggling dark mode.
 *
 * Syncs the `dark` class on <html> and persists the preference to localStorage
 * so it survives page reloads.
 */
export function useDarkMode(): UseDarkModeReturn {
  const [isDark, setIsDark] = useState<boolean>(getInitialDark);

  // Apply class whenever state changes
  useEffect(() => {
    applyDark(isDark);
    try {
      localStorage.setItem(STORAGE_KEY, String(isDark));
    } catch {
      // Silently ignore localStorage errors
    }
  }, [isDark]);

  // Apply the initial class synchronously before first paint to avoid flash
  useEffect(() => {
    applyDark(isDark);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = () => setIsDark((prev) => !prev);
  const setDark = (value: boolean) => setIsDark(value);

  return { isDark, toggle, setDark };
}
