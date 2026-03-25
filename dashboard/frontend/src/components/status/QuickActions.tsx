/**
 * QuickActions — row of three large shortcut buttons on the Dashboard.
 *
 * Provides one-tap navigation to the Tests page for the most common
 * operational tasks: audio testing, dispatch testing, and simulated
 * MQTT detection. These are read-only nav buttons — no backend calls are
 * made from this component.
 *
 * Layout: horizontal row on desktop, 2-column grid on mobile.
 * Primary action (Test Audio) uses a filled blue style; the other two use a
 * subtle outline treatment to create visual hierarchy.
 */

import type { ElementType } from 'react';
import { Volume2, Mic, Eye } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@/utils/cn';

interface QuickActionDef {
  label: string;
  description: string;
  icon: ElementType;
  to: string;
  primary?: boolean;
}

const ACTIONS: QuickActionDef[] = [
  {
    label: 'Test Audio',
    description: 'Push a live audio clip',
    icon: Volume2,
    to: '/tests',
    primary: true,
  },
  {
    label: 'Test Dispatch',
    description: 'Preview dispatch mode',
    icon: Mic,
    to: '/tests',
  },
  {
    label: 'Simulate Detection',
    description: 'Fire an MQTT event',
    icon: Eye,
    to: '/tests#mqtt',
  },
];

/**
 * Quick-action button row for the Dashboard monitoring view.
 *
 * Renders three large nav buttons below the recent-activity feed.
 * Clicking any button navigates to the appropriate section of the Tests page.
 */
export function QuickActions() {
  const navigate = useNavigate();

  return (
    <div
      className="grid grid-cols-1 gap-3 sm:grid-cols-3"
      aria-label="Quick actions"
    >
      {ACTIONS.map(({ label, description, icon: Icon, to, primary }) => (
        <button
          key={label}
          type="button"
          onClick={() => navigate(to)}
          className={cn(
            'flex items-center gap-3 rounded-2xl px-5 py-4 text-left transition-all duration-200',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
            primary
              ? [
                  'bg-blue-600 text-white shadow-md shadow-blue-900/30',
                  'hover:bg-blue-500 hover:shadow-lg hover:shadow-blue-900/40 hover:-translate-y-0.5',
                ]
              : [
                  'border border-gray-200 bg-white text-gray-700 dark:border-gray-700/60 dark:bg-gray-900/50 dark:text-gray-200',
                  'hover:border-gray-300 hover:bg-gray-50 dark:hover:border-gray-600 dark:hover:bg-gray-800/60 hover:-translate-y-0.5',
                  'hover:shadow-md hover:shadow-gray-200/40 dark:hover:shadow-gray-900/40',
                ],
          )}
        >
          <Icon
            className={cn(
              'h-5 w-5 flex-shrink-0',
              primary ? 'text-blue-200' : 'text-gray-400 dark:text-gray-400',
            )}
            aria-hidden="true"
          />
          <div className="min-w-0">
            <p className="text-sm font-semibold">{label}</p>
            <p
              className={cn(
                'text-xs',
                primary ? 'text-blue-200' : 'text-gray-500 dark:text-gray-500',
              )}
            >
              {description}
            </p>
          </div>
        </button>
      ))}
    </div>
  );
}
