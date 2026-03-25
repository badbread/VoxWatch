/**
 * RawConfigEditor — in-browser YAML editor with syntax highlighting
 * using CodeMirror 6. Lightweight (~150KB vs Monaco's 3MB+).
 *
 * Features: YAML syntax coloring, line numbers, dark/light theme,
 * bracket matching, and file path info for SSH users.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { Save, RotateCcw, Terminal, AlertCircle, CheckCircle, Loader } from 'lucide-react';
import { Card } from '@/components/common/Card';
import { useDarkMode } from '@/hooks/useDarkMode';
import apiClient from '@/api/client';

// CodeMirror imports — modular, only load what we need
import { EditorView, basicSetup } from 'codemirror';
import { EditorState } from '@codemirror/state';
import { yaml } from '@codemirror/lang-yaml';
import { oneDark } from '@codemirror/theme-one-dark';

/**
 * Advanced raw YAML config editor with CodeMirror 6.
 */
export function RawConfigEditor() {
  const [content, setContent] = useState('');
  const [originalContent, setOriginalContent] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const { isDark } = useDarkMode();
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const editorViewRef = useRef<EditorView | null>(null);

  // Load raw config
  useEffect(() => {
    const load = async () => {
      try {
        const resp = await apiClient.get('/config/raw');
        const text = typeof resp.data === 'string' ? resp.data : JSON.stringify(resp.data, null, 2);
        setContent(text);
        setOriginalContent(text);
      } catch {
        try {
          const resp = await apiClient.get('/config');
          const text = JSON.stringify(resp.data, null, 2);
          setContent(text);
          setOriginalContent(text);
        } catch {
          setError('Could not load configuration.');
        }
      } finally {
        setIsLoading(false);
      }
    };
    void load();
  }, []);

  // Initialize CodeMirror editor
  const initEditor = useCallback(
    (container: HTMLDivElement, initialContent?: string) => {
      // Destroy previous instance
      if (editorViewRef.current) {
        editorViewRef.current.destroy();
      }

      // Use explicit initialContent if provided (e.g. on discard),
      // otherwise fall back to current content state.
      const doc = initialContent ?? content;

      const extensions = [
        basicSetup,
        yaml(),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            setContent(update.state.doc.toString());
            setError(null);
          }
        }),
        EditorView.theme({
          '&': { height: '550px', fontSize: '13px' },
          '.cm-scroller': { overflow: 'auto', fontFamily: "'JetBrains Mono', 'Fira Code', monospace" },
          '.cm-content': { padding: '12px 0' },
        }),
      ];

      if (isDark) {
        extensions.push(oneDark);
      }

      const state = EditorState.create({
        doc,
        extensions,
      });

      editorViewRef.current = new EditorView({
        state,
        parent: container,
      });
    },
    [content, isDark],
  );

  // Mount/remount editor when content loads or theme changes
  useEffect(() => {
    if (!isLoading && editorContainerRef.current && content) {
      initEditor(editorContainerRef.current);
    }
    return () => {
      editorViewRef.current?.destroy();
      editorViewRef.current = null;
    };
    // Only re-init on theme change or initial load, not on every keystroke
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, isDark]);

  const isDirty = content !== originalContent;

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const parsed = JSON.parse(content);
      await apiClient.put('/config', parsed);
      setOriginalContent(content);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Save failed. Check syntax.';
      setError(msg);
    } finally {
      setIsSaving(false);
    }
  };

  const handleDiscard = () => {
    setContent(originalContent);
    setError(null);
    // Pass originalContent explicitly to avoid stale closure —
    // setContent is async and initEditor's closure still has the old content.
    if (editorContainerRef.current) {
      initEditor(editorContainerRef.current, originalContent);
    }
  };

  if (isLoading) {
    return (
      <Card>
        <div className="flex items-center justify-center py-12">
          <Loader className="h-6 w-6 animate-spin text-gray-400" />
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* File path info */}
      <Card>
        <div className="flex items-start gap-3">
          <Terminal className="mt-0.5 h-4 w-4 flex-shrink-0 text-gray-400" />
          <div>
            <p className="text-sm text-gray-700 dark:text-gray-300">
              Config file:{' '}
              <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs dark:bg-gray-800">
                /config/config.yaml
              </code>
            </p>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Also editable via SSH or volume mount. Restart VoxWatch after saving.
            </p>
          </div>
        </div>
      </Card>

      {/* CodeMirror editor */}
      <Card title="config.yaml" noPadding>
        <div
          ref={editorContainerRef}
          className="overflow-hidden rounded-b-xl"
        />
      </Card>

      {/* Status + actions */}
      {(isDirty || error || success) && (
        <div className="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-4 py-3 dark:border-gray-700/50 dark:bg-gray-900">
          <div className="flex items-center gap-2">
            {error ? (
              <>
                <AlertCircle className="h-4 w-4 text-red-500" />
                <span className="text-sm text-red-600 dark:text-red-400">{error}</span>
              </>
            ) : success ? (
              <>
                <CheckCircle className="h-4 w-4 text-green-500" />
                <span className="text-sm text-green-700 dark:text-green-400">Configuration saved</span>
              </>
            ) : (
              <>
                <AlertCircle className="h-4 w-4 text-yellow-500" />
                <span className="text-sm text-yellow-700 dark:text-yellow-400">Unsaved changes</span>
              </>
            )}
          </div>
          {isDirty && (
            <div className="flex items-center gap-2">
              <button
                onClick={handleDiscard}
                disabled={isSaving}
                className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Discard
              </button>
              <button
                onClick={() => void handleSave()}
                disabled={isSaving}
                className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {isSaving ? <Loader className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                Save
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
