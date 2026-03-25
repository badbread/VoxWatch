/**
 * NotFoundPage — 404 error page.
 *
 * Renders when no route matches the current URL. Provides a home link to
 * recover navigation.
 */

import { Link } from 'react-router-dom';
import { ShieldOff } from 'lucide-react';

/**
 * 404 Not Found page.
 */
export function NotFoundPage() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <div className="mb-6 rounded-full bg-gray-100 p-6 dark:bg-gray-800">
        <ShieldOff className="h-12 w-12 text-gray-400" />
      </div>
      <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">
        404
      </h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
        Page not found. The route you're looking for doesn't exist.
      </p>
      <Link
        to="/"
        className="mt-6 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
      >
        Back to Dashboard
      </Link>
    </div>
  );
}
