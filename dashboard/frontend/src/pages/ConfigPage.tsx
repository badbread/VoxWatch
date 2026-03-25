/**
 * ConfigPage — configuration editor page with form view and advanced raw YAML editor.
 */

import { useState } from 'react';
import { Settings, Code } from 'lucide-react';
import { cn } from '@/utils/cn';
import { ConfigEditor } from '@/components/config/ConfigEditor';
import { RawConfigEditor } from '@/components/config/RawConfigEditor';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';

/**
 * Configuration editor page with form/advanced toggle.
 */
export function ConfigPage() {
  const [mode, setMode] = useState<'form' | 'raw'>('form');

  return (
    <ErrorBoundary>
      <div className="space-y-4">
        {/* Mode toggle */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-lg border border-gray-200 bg-gray-100 p-0.5 dark:border-gray-700 dark:bg-gray-800">
              <button
                onClick={() => setMode('form')}
                className={cn(
                  'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                  mode === 'form'
                    ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-gray-100'
                    : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200',
                )}
              >
                <Settings className="h-3.5 w-3.5" />
                Form Editor
              </button>
              <button
                onClick={() => setMode('raw')}
                className={cn(
                  'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                  mode === 'raw'
                    ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-gray-100'
                    : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200',
                )}
              >
                <Code className="h-3.5 w-3.5" />
                Advanced (YAML)
              </button>
            </div>
          </div>
        </div>

        {/* Editor */}
        {mode === 'form' ? (
          <ConfigEditor />
        ) : (
          <RawConfigEditor />
        )}
      </div>
    </ErrorBoundary>
  );
}
