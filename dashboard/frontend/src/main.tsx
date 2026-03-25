/**
 * Application entry point.
 *
 * Mounts the React app into the #root element. The dark class is applied
 * synchronously before React renders (via useDarkMode on first call) to
 * prevent a flash of the wrong theme.
 */

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App';

// Apply dark class before first render to avoid flash
const stored = localStorage.getItem('voxwatch-dark-mode');
const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
if (stored === 'true' || (stored === null && systemDark)) {
  document.documentElement.classList.add('dark');
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Root element #root not found. Check index.html.');
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
