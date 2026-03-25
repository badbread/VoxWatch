/**
 * RawConfigEditor — Monaco-based YAML editor for the Advanced tab.
 *
 * Features:
 *  - Monaco Editor (VS Code engine) with YAML language support
 *  - Real-time YAML validation via js-yaml with inline error markers
 *  - Dark/light theme that follows the dashboard's Tailwind dark mode
 *  - Status bar showing file path, YAML validity, and cursor position
 *  - Diff view toggled by "Show Changes" button
 *  - Keyboard shortcuts: Ctrl+S save, find/replace, undo/redo (Monaco built-ins)
 *  - Mobile-aware: larger font and no minimap on small viewports
 *  - Loading skeleton while Monaco initialises
 *
 * Save flow:
 *   YAML content → js-yaml.load() → plain JS object → PUT /api/config (JSON body)
 *   The backend's PUT /api/config expects a Dict[str, Any], not raw YAML text.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import Editor, { DiffEditor, useMonaco } from '@monaco-editor/react';
import type { editor as MonacoEditor } from 'monaco-editor';
import * as yaml from 'js-yaml';
import { Save, RotateCcw, Terminal, AlertCircle, CheckCircle, Loader, GitCompare } from 'lucide-react';
import { Card } from '@/components/common/Card';
import { useDarkMode } from '@/hooks/useDarkMode';
import apiClient from '@/api/client';
import { cn } from '@/utils/cn';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CursorPosition {
  line: number;
  column: number;
}

interface YamlValidationResult {
  valid: boolean;
  /** Number of errors (0 = valid). */
  errorCount: number;
  /** Human-readable message for the first error, if any. */
  message: string | null;
  /** 1-based line number where the error was detected, or null. */
  errorLine: number | null;
}

// ---------------------------------------------------------------------------
// Monaco theme registration
// ---------------------------------------------------------------------------

const VOXWATCH_DARK_THEME = 'voxwatch-dark';
const VOXWATCH_LIGHT_THEME = 'voxwatch-light';

/**
 * Register custom Monaco themes that match the VoxWatch dashboard palette.
 * Called once when Monaco is ready. Subsequent calls are ignored by Monaco.
 */
function registerThemes(monacoInstance: typeof import('monaco-editor')): void {
  monacoInstance.editor.defineTheme(VOXWATCH_DARK_THEME, {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'key.yaml', foreground: '7dd3fc' },           // sky-300 — YAML keys
      { token: 'string.yaml', foreground: '86efac' },         // green-300 — string values
      { token: 'number.yaml', foreground: 'fbbf24' },         // amber-400 — numbers
      { token: 'keyword.yaml', foreground: 'c084fc' },        // purple-400 — booleans / null
      { token: 'comment.yaml', foreground: '6b7280', fontStyle: 'italic' }, // gray-500
    ],
    colors: {
      'editor.background': '#111827',             // gray-900
      'editor.foreground': '#f9fafb',             // gray-50
      'editor.lineHighlightBackground': '#1f2937', // gray-800
      'editor.selectionBackground': '#1d4ed880',  // blue-700/50
      'editorLineNumber.foreground': '#4b5563',   // gray-600
      'editorLineNumber.activeForeground': '#9ca3af', // gray-400
      'editorIndentGuide.background': '#374151',  // gray-700
      'editorCursor.foreground': '#60a5fa',       // blue-400
      'scrollbarSlider.background': '#374151',
      'scrollbarSlider.hoverBackground': '#4b5563',
    },
  });

  monacoInstance.editor.defineTheme(VOXWATCH_LIGHT_THEME, {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'key.yaml', foreground: '1d4ed8' },     // blue-700
      { token: 'string.yaml', foreground: '15803d' },  // green-700
      { token: 'number.yaml', foreground: 'd97706' },  // amber-600
      { token: 'keyword.yaml', foreground: '7c3aed' }, // violet-600
      { token: 'comment.yaml', foreground: '9ca3af', fontStyle: 'italic' },
    ],
    colors: {
      'editor.background': '#ffffff',
      'editor.foreground': '#111827',
      'editor.lineHighlightBackground': '#f9fafb',
      'editorLineNumber.foreground': '#9ca3af',
      'editorLineNumber.activeForeground': '#4b5563',
    },
  });
}

// ---------------------------------------------------------------------------
// YAML validation helper
// ---------------------------------------------------------------------------

/**
 * Parse YAML and return a structured validation result.
 * Uses js-yaml in safe mode; never executes arbitrary code.
 */
function validateYaml(text: string): YamlValidationResult {
  if (!text.trim()) {
    return { valid: false, errorCount: 1, message: 'Config is empty.', errorLine: 1 };
  }
  try {
    yaml.load(text, { schema: yaml.DEFAULT_SCHEMA });
    return { valid: true, errorCount: 0, message: null, errorLine: null };
  } catch (err: unknown) {
    if (err instanceof yaml.YAMLException) {
      const line = err.mark?.line != null ? err.mark.line + 1 : null;
      return {
        valid: false,
        errorCount: 1,
        // Strip the verbose "YAMLException:" prefix for the status bar
        message: err.reason ?? err.message,
        errorLine: line,
      };
    }
    return { valid: false, errorCount: 1, message: String(err), errorLine: null };
  }
}

/**
 * Push YAML validation errors into Monaco's model marker system so they
 * appear as red squiggly underlines with tooltip messages.
 */
function applyYamlMarkers(
  monacoInstance: typeof import('monaco-editor'),
  model: MonacoEditor.ITextModel,
  validation: YamlValidationResult,
): void {
  if (validation.valid || !validation.message) {
    monacoInstance.editor.setModelMarkers(model, 'yaml-lint', []);
    return;
  }

  const line = validation.errorLine ?? 1;
  const lineContent = model.getLineContent(Math.min(line, model.getLineCount()));
  const startColumn = lineContent.search(/\S/) + 1 || 1; // first non-whitespace

  monacoInstance.editor.setModelMarkers(model, 'yaml-lint', [
    {
      severity: monacoInstance.MarkerSeverity.Error,
      message: validation.message,
      startLineNumber: line,
      startColumn,
      endLineNumber: line,
      endColumn: lineContent.length + 1,
    },
  ]);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Full-featured Monaco YAML editor for the Advanced Config tab.
 *
 * Fetches the config as raw YAML text from GET /api/config/raw, lets the
 * user edit it with VS Code-grade tooling, then saves by parsing the YAML
 * to a JS object and sending it to PUT /api/config as JSON.
 */
export function RawConfigEditor() {
  const [content, setContent] = useState('');
  const [originalContent, setOriginalContent] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [cursor, setCursor] = useState<CursorPosition>({ line: 1, column: 1 });
  const [isMobile, setIsMobile] = useState(false);

  const { isDark } = useDarkMode();
  const monaco = useMonaco();

  // Ref to the live editor instance so we can imperatively set markers etc.
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null);

  // Derived YAML validation — recomputed on every content change
  const validation = validateYaml(content);
  const isDirty = content !== originalContent;

  // -------------------------------------------------------------------------
  // Mobile detection
  // -------------------------------------------------------------------------
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 640px)');
    setIsMobile(mq.matches);
    const listener = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener('change', listener);
    return () => mq.removeEventListener('change', listener);
  }, []);

  // -------------------------------------------------------------------------
  // Load config on mount
  // -------------------------------------------------------------------------
  useEffect(() => {
    const load = async () => {
      setIsLoading(true);
      try {
        // GET /api/config/raw returns plain-text YAML
        const resp = await apiClient.get<string>('/config/raw', {
          headers: { Accept: 'text/yaml, text/plain, */*' },
          transformResponse: (data: string) => data, // prevent axios JSON-parsing
        });
        const text = typeof resp.data === 'string' ? resp.data : JSON.stringify(resp.data, null, 2);
        setContent(text);
        setOriginalContent(text);
      } catch {
        // Fallback: GET /api/config returns JSON — convert to YAML for display
        try {
          const resp = await apiClient.get<Record<string, unknown>>('/config');
          const text = yaml.dump(resp.data, { lineWidth: 120, noRefs: true });
          setContent(text);
          setOriginalContent(text);
        } catch {
          const errMsg = '# Error: could not load configuration.\n';
          setContent(errMsg);
          setOriginalContent(errMsg);
        }
      } finally {
        setIsLoading(false);
      }
    };
    void load();
  }, []);

  // -------------------------------------------------------------------------
  // Register custom themes once Monaco is ready
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (monaco) {
      registerThemes(monaco);
    }
  }, [monaco]);

  // -------------------------------------------------------------------------
  // Re-apply markers whenever content or monaco instance changes
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!monaco || !editorRef.current) return;
    const model = editorRef.current.getModel();
    if (!model) return;
    applyYamlMarkers(monaco, model, validation);
  }, [content, validation, monaco]);

  // -------------------------------------------------------------------------
  // Ctrl+S / Cmd+S keyboard shortcut
  // -------------------------------------------------------------------------
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (isDirty && validation.valid && !isSaving) {
          void handleSave();
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
    // handleSave is stable via useCallback, listed to avoid lint warnings
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDirty, validation.valid, isSaving]);

  // -------------------------------------------------------------------------
  // Save handler
  // -------------------------------------------------------------------------

  /**
   * Parse the current YAML content to a plain JS dict and PUT it to the
   * backend. The backend's PUT /api/config expects a JSON body (Dict[str, Any]),
   * not raw YAML text — js-yaml.load() converts between the two.
   */
  const handleSave = useCallback(async () => {
    if (!validation.valid) return;
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      // Parse YAML → JS object (this is what the backend actually wants)
      const parsed = yaml.load(content, { schema: yaml.DEFAULT_SCHEMA }) as Record<string, unknown>;
      await apiClient.put('/config', parsed);
      setOriginalContent(content);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      const axiosDetail =
        (err as { response?: { data?: { detail?: { message?: string } | string } } })?.response?.data?.detail;
      const msg =
        typeof axiosDetail === 'object' && axiosDetail !== null
          ? (axiosDetail as { message?: string }).message ?? 'Save failed.'
          : typeof axiosDetail === 'string'
            ? axiosDetail
            : err instanceof Error
              ? err.message
              : 'Save failed.';
      setSaveError(msg);
    } finally {
      setIsSaving(false);
    }
  }, [content, validation.valid]);

  // -------------------------------------------------------------------------
  // Discard handler
  // -------------------------------------------------------------------------
  const handleDiscard = useCallback(() => {
    setContent(originalContent);
    setSaveError(null);
    setSaveSuccess(false);
    // Directly update the editor model to avoid a remount
    if (editorRef.current) {
      const model = editorRef.current.getModel();
      if (model) {
        model.setValue(originalContent);
      }
    }
  }, [originalContent]);

  // -------------------------------------------------------------------------
  // Monaco editor mount callback
  // -------------------------------------------------------------------------
  const handleEditorMount = useCallback(
    (editorInstance: MonacoEditor.IStandaloneCodeEditor) => {
      editorRef.current = editorInstance;

      // Track cursor position for the status bar
      editorInstance.onDidChangeCursorPosition((e) => {
        setCursor({ line: e.position.lineNumber, column: e.position.column });
      });

      // Apply initial markers for whatever content loaded
      if (monaco) {
        const model = editorInstance.getModel();
        if (model) {
          applyYamlMarkers(monaco, model, validateYaml(content));
        }
      }
    },
    // content is captured at mount time intentionally; markers update separately
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [monaco],
  );

  // -------------------------------------------------------------------------
  // Derived values
  // -------------------------------------------------------------------------
  const monacoTheme = isDark ? VOXWATCH_DARK_THEME : VOXWATCH_LIGHT_THEME;
  const editorFontSize = isMobile ? 15 : 13;

  /**
   * Shared Monaco editor options.
   * minimap is disabled on mobile screens and in diff view to save space.
   */
  const editorOptions: MonacoEditor.IStandaloneEditorConstructionOptions = {
    language: 'yaml',
    fontSize: editorFontSize,
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
    fontLigatures: true,
    lineNumbers: 'on',
    minimap: { enabled: !isMobile && !showDiff },
    wordWrap: 'off',
    bracketPairColorization: { enabled: true },
    matchBrackets: 'always',
    automaticLayout: true,         // resize with container
    scrollBeyondLastLine: false,
    tabSize: 2,
    insertSpaces: true,
    renderLineHighlight: 'line',
    cursorBlinking: 'smooth',
    smoothScrolling: true,
    padding: { top: 12, bottom: 12 },
    // Inlay hints clutter YAML — disable
    inlayHints: { enabled: 'off' },
    // Suggestions are less useful for YAML config files
    quickSuggestions: false,
  };

  // -------------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------------
  if (isLoading) {
    return (
      <div className="space-y-4">
        <Card>
          <div className="flex items-center gap-3">
            <Terminal className="h-4 w-4 text-gray-400" />
            <div className="h-4 w-48 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
          </div>
        </Card>
        <Card title="config.yaml" noPadding>
          <div className="flex h-[550px] items-center justify-center rounded-b-xl bg-gray-900">
            <Loader className="h-6 w-6 animate-spin text-gray-500" />
          </div>
        </Card>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <div className="space-y-4">
      {/* ------------------------------------------------------------------ */}
      {/* File path info card                                                 */}
      {/* ------------------------------------------------------------------ */}
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
              Also editable via SSH or volume mount. Ctrl+S to save. Restart VoxWatch after saving.
            </p>
          </div>
        </div>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Editor card                                                         */}
      {/* ------------------------------------------------------------------ */}
      <Card noPadding>
        {/* Card header — title + diff toggle */}
        <div className="flex items-center justify-between rounded-t-xl border-b border-gray-200 px-4 py-2.5 dark:border-gray-700/50">
          <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">config.yaml</span>
          <button
            type="button"
            onClick={() => setShowDiff((v) => !v)}
            disabled={!isDirty}
            title={isDirty ? 'Toggle diff view' : 'No changes to diff'}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors',
              showDiff
                ? 'bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300'
                : 'text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800',
              !isDirty && 'cursor-not-allowed opacity-40',
            )}
          >
            <GitCompare className="h-3.5 w-3.5" />
            {showDiff ? 'Hide Changes' : 'Show Changes'}
          </button>
        </div>

        {/* Monaco editor — standard or diff */}
        <div className="rounded-b-xl overflow-hidden">
          {showDiff ? (
            /**
             * DiffEditor shows original (saved) vs current (edited) side-by-side.
             * original = what's on disk; modified = user's edits.
             */
            <DiffEditor
              height="550px"
              language="yaml"
              theme={monacoTheme}
              original={originalContent}
              modified={content}
              options={{
                ...editorOptions,
                readOnly: false,           // allow editing in modified pane
                renderSideBySide: !isMobile, // inline diff on mobile
              }}
              onMount={(diffEditorInstance) => {
                // Track cursor in the modified (right-hand) pane
                const modifiedEditor = diffEditorInstance.getModifiedEditor();
                modifiedEditor.onDidChangeCursorPosition((e) => {
                  setCursor({ line: e.position.lineNumber, column: e.position.column });
                });
                // Sync edits in the diff editor's modified pane back to state
                modifiedEditor.onDidChangeModelContent(() => {
                  const newVal = modifiedEditor.getValue();
                  setContent(newVal);
                  if (monaco) {
                    const model = modifiedEditor.getModel();
                    if (model) applyYamlMarkers(monaco, model, validateYaml(newVal));
                  }
                });
              }}
              loading={
                <div className="flex h-[550px] items-center justify-center bg-gray-900">
                  <Loader className="h-6 w-6 animate-spin text-gray-500" />
                </div>
              }
            />
          ) : (
            <Editor
              height="550px"
              language="yaml"
              theme={monacoTheme}
              value={content}
              options={editorOptions}
              onChange={(value) => {
                // value can be undefined if Monaco hasn't initialised the model yet
                if (value !== undefined) {
                  setContent(value);
                  setSaveError(null);
                }
              }}
              onMount={handleEditorMount}
              loading={
                <div className="flex h-[550px] items-center justify-center bg-gray-900">
                  <Loader className="h-6 w-6 animate-spin text-gray-500" />
                </div>
              }
            />
          )}
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Status bar — mimics VS Code's bottom bar                         */}
        {/* ---------------------------------------------------------------- */}
        <div
          className={cn(
            'flex items-center justify-between rounded-b-xl border-t px-3 py-1.5 font-mono text-xs',
            isDark
              ? 'border-gray-700/50 bg-[#0d1117] text-gray-400'
              : 'border-gray-200 bg-gray-50 text-gray-500',
          )}
        >
          {/* Left — file path */}
          <span className="hidden sm:block">/config/config.yaml</span>

          {/* Center — validation status */}
          <span
            className={cn(
              'flex items-center gap-1 font-sans font-medium',
              validation.valid ? 'text-green-500' : 'text-red-500',
            )}
          >
            {validation.valid ? (
              <>
                <CheckCircle className="h-3 w-3" />
                Valid YAML
              </>
            ) : (
              <>
                <AlertCircle className="h-3 w-3" />
                {validation.errorCount} error{validation.errorCount !== 1 ? 's' : ''}
              </>
            )}
          </span>

          {/* Right — cursor position */}
          <span>
            Ln {cursor.line}, Col {cursor.column}
          </span>
        </div>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* YAML parse error detail banner (shown below editor)                */}
      {/* ------------------------------------------------------------------ */}
      {!validation.valid && validation.message && (
        <div className="flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 dark:border-red-800/40 dark:bg-red-950/20">
          <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-500" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-red-700 dark:text-red-400">YAML syntax error</p>
            <p className="mt-0.5 font-mono text-xs text-red-600 dark:text-red-300">{validation.message}</p>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Backend save error banner                                           */}
      {/* ------------------------------------------------------------------ */}
      {saveError && (
        <div className="flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 dark:border-red-800/40 dark:bg-red-950/20">
          <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-500" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-red-700 dark:text-red-400">Save failed</p>
            <p className="mt-0.5 text-xs text-red-600 dark:text-red-300">{saveError}</p>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Action bar (visible only when dirty or success)                    */}
      {/* ------------------------------------------------------------------ */}
      {(isDirty || saveSuccess) && (
        <div className="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-4 py-3 dark:border-gray-700/50 dark:bg-gray-900">
          {/* Status message */}
          <div className="flex items-center gap-2">
            {saveSuccess ? (
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

          {/* Discard + Save buttons */}
          {isDirty && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleDiscard}
                disabled={isSaving}
                className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Discard
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={isSaving || !validation.valid}
                title={!validation.valid ? 'Fix YAML errors before saving' : undefined}
                className={cn(
                  'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-white',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
                  'disabled:cursor-not-allowed disabled:opacity-50',
                  !validation.valid ? 'bg-gray-400' : 'bg-blue-600 hover:bg-blue-700',
                )}
              >
                {isSaving ? (
                  <Loader className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                Save
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
