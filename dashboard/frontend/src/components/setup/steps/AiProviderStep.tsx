/**
 * AiProviderStep — AI vision provider selection and credential entry.
 *
 * Provider list mirrors the PROVIDERS array from AiConfigForm so the same
 * models are available in the wizard. A "Skip AI" option is provided with a
 * warning that AI-generated descriptions won't be available.
 *
 * When a cloud provider is selected: API key input + model dropdown.
 * When Ollama is selected: host URL input.
 * When "none" is selected: no additional fields.
 */

import { useState } from 'react';
import {
  Brain,
  Key,
  Server,
  FlaskConical,
  CheckCircle,
  XCircle,
  Loader,
  ArrowRight,
  AlertTriangle,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { cn } from '@/utils/cn';
import { testAiProvider } from '@/api/status';

/** Props for AiProviderStep. */
interface AiProviderStepProps {
  provider: string;
  model: string;
  apiKey: string;
  aiHost: string;
  onNext: (provider: string, model: string, apiKey: string, host: string) => void;
}

// ---------------------------------------------------------------------------
// Provider metadata (subset matching AiConfigForm)
// ---------------------------------------------------------------------------

interface ModelInfo {
  id: string;
  name: string;
  recommended?: boolean;
}

interface ProviderDef {
  id: string;
  name: string;
  icon: string;
  needsApiKey: boolean;
  needsHost: boolean;
  defaultHost?: string;
  models: ModelInfo[];
}

const AI_PROVIDERS: ProviderDef[] = [
  {
    id: 'gemini',
    name: 'Google Gemini',
    icon: '🔮',
    needsApiKey: true,
    needsHost: false,
    models: [
      { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash', recommended: true },
      { id: 'gemini-2.5-flash-lite', name: 'Gemini 2.5 Flash Lite' },
      { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro' },
    ],
  },
  {
    id: 'openai',
    name: 'OpenAI',
    icon: '🤖',
    needsApiKey: true,
    needsHost: false,
    models: [
      { id: 'gpt-4o-mini', name: 'GPT-4o Mini', recommended: true },
      { id: 'gpt-4o', name: 'GPT-4o' },
      { id: 'o4-mini', name: 'o4-mini' },
    ],
  },
  {
    id: 'anthropic',
    name: 'Anthropic Claude',
    icon: '🧠',
    needsApiKey: true,
    needsHost: false,
    models: [
      { id: 'claude-haiku-4-5', name: 'Claude Haiku 4.5', recommended: true },
      { id: 'claude-sonnet-4-6', name: 'Claude Sonnet 4.6' },
    ],
  },
  {
    id: 'grok',
    name: 'xAI Grok',
    icon: '⚡',
    needsApiKey: true,
    needsHost: false,
    models: [
      { id: 'grok-2-vision-1212', name: 'Grok 2 Vision', recommended: true },
      { id: 'grok-2-vision-mini', name: 'Grok 2 Vision Mini' },
    ],
  },
  {
    id: 'ollama',
    name: 'Ollama (local)',
    icon: '🏠',
    needsApiKey: false,
    needsHost: true,
    defaultHost: 'http://localhost:11434',
    models: [
      { id: 'llava:7b', name: 'LLaVA 7B', recommended: true },
      { id: 'llava:13b', name: 'LLaVA 13B' },
      { id: 'moondream', name: 'Moondream (tiny)' },
    ],
  },
  {
    id: 'none',
    name: 'Skip AI (no descriptions)',
    icon: '—',
    needsApiKey: false,
    needsHost: false,
    models: [],
  },
];

const inputCls = cn(
  'w-full rounded-lg border bg-gray-800 px-3 py-3 text-base text-gray-100',
  'border-gray-600 placeholder-gray-500',
  'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50',
  'transition-colors',
);

/**
 * AI provider picker with conditional API key / host fields.
 *
 * @example
 *   <AiProviderStep provider="gemini" model="gemini-2.5-flash" apiKey="" aiHost="" onNext={...} />
 */
export function AiProviderStep({
  provider: initialProvider,
  model: initialModel,
  apiKey: initialApiKey,
  aiHost: initialHost,
  onNext,
}: AiProviderStepProps) {
  const [provider, setProvider] = useState(initialProvider);
  const [model, setModel] = useState(initialModel);
  const [apiKey, setApiKey] = useState(initialApiKey);
  const [host, setHost] = useState(initialHost);

  const providerDef = AI_PROVIDERS.find((p) => p.id === provider);

  const handleProviderChange = (newId: string) => {
    setProvider(newId);
    const def = AI_PROVIDERS.find((p) => p.id === newId);
    const defaultModel = def?.models.find((m) => m.recommended) ?? def?.models[0];
    setModel(defaultModel?.id ?? '');
    if (def?.needsHost) setHost(def.defaultHost ?? '');
    else setHost('');
    setApiKey('');
  };

  const testMutation = useMutation({
    mutationFn: () =>
      testAiProvider({
        provider,
        model,
        ...(apiKey ? { api_key: apiKey } : {}),
        ...(host ? { host } : {}),
      }),
  });

  const canTest = provider !== 'none' && (!providerDef?.needsApiKey || apiKey.trim().length > 0);
  const canContinue = provider === 'none' || (!providerDef?.needsApiKey || apiKey.trim().length > 0);

  return (
    <div className="space-y-6 px-6 py-8">
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-600/20 text-indigo-400">
          <Brain className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-100">AI vision provider</h2>
          <p className="mt-1 text-sm text-gray-400">
            VoxWatch uses AI to describe what it sees and craft personalised warnings.
            Google Gemini is recommended — free API key available.
          </p>
        </div>
      </div>

      {/* Provider selector cards */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {AI_PROVIDERS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => handleProviderChange(p.id)}
            className={cn(
              'flex flex-col items-center gap-1.5 rounded-xl border px-3 py-3 text-sm font-medium transition-all',
              'focus:outline-none focus:ring-2 focus:ring-blue-500',
              provider === p.id
                ? 'border-blue-500 bg-blue-900/30 text-blue-300'
                : 'border-gray-700 bg-gray-800/50 text-gray-400 hover:border-gray-500 hover:text-gray-200',
            )}
          >
            <span className="text-xl" aria-hidden="true">{p.icon}</span>
            <span className="text-center leading-tight">{p.name}</span>
          </button>
        ))}
      </div>

      {/* Skip AI warning */}
      {provider === 'none' && (
        <div className="flex items-start gap-2 rounded-lg bg-amber-950/40 px-4 py-3 text-sm text-amber-300 border border-amber-800/50">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Without AI, VoxWatch will use generic pre-written messages instead of personalised descriptions.
            You can configure AI later in Settings.
          </span>
        </div>
      )}

      {/* Model selector */}
      {providerDef && providerDef.models.length > 0 && (
        <div>
          <label htmlFor="ai-model" className="mb-1.5 block text-sm font-medium text-gray-300">
            Model
          </label>
          <select
            id="ai-model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className={inputCls}
          >
            {providerDef.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}{m.recommended ? ' (Recommended)' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Host URL for Ollama */}
      {providerDef?.needsHost && (
        <div>
          <label htmlFor="ai-host" className="mb-1.5 block text-sm font-medium text-gray-300">
            <span className="flex items-center gap-1.5">
              <Server className="h-3.5 w-3.5" />
              Host URL
            </span>
          </label>
          <input
            id="ai-host"
            type="url"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder={providerDef.defaultHost ?? 'http://localhost:11434'}
            className={inputCls}
          />
        </div>
      )}

      {/* API key for cloud providers */}
      {providerDef?.needsApiKey && (
        <div>
          <label htmlFor="ai-key" className="mb-1.5 block text-sm font-medium text-gray-300">
            <span className="flex items-center gap-1.5">
              <Key className="h-3.5 w-3.5" />
              API key
            </span>
          </label>
          <input
            id="ai-key"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={`Paste your ${providerDef.name} API key`}
            autoComplete="off"
            className={inputCls}
          />
          <p className="mt-1 text-xs text-gray-500">
            Your key is stored only in config.yaml on your server. It is never sent to us.
          </p>
        </div>
      )}

      {/* Test connection */}
      {provider !== 'none' && (
        <button
          type="button"
          onClick={() => testMutation.mutate()}
          disabled={testMutation.isPending || !canTest}
          className={cn(
            'flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold',
            'border transition-all duration-150 active:scale-[0.98]',
            'focus:outline-none focus:ring-2 focus:ring-blue-500',
            'disabled:cursor-not-allowed disabled:opacity-50',
            testMutation.isSuccess && testMutation.data?.success
              ? 'border-green-600 bg-green-900/20 text-green-300'
              : testMutation.isSuccess && !testMutation.data?.success
                ? 'border-red-700 bg-red-950/20 text-red-300'
                : 'border-gray-600 bg-gray-800 text-gray-300 hover:bg-gray-700',
          )}
        >
          {testMutation.isPending ? (
            <Loader className="h-4 w-4 animate-spin" />
          ) : testMutation.isSuccess && testMutation.data?.success ? (
            <CheckCircle className="h-4 w-4" />
          ) : testMutation.isSuccess && !testMutation.data?.success ? (
            <XCircle className="h-4 w-4" />
          ) : (
            <FlaskConical className="h-4 w-4" />
          )}
          {testMutation.isPending
            ? 'Testing...'
            : testMutation.isSuccess && testMutation.data?.success
              ? `Connected (${testMutation.data.response_time_ms}ms)`
              : testMutation.isSuccess && !testMutation.data?.success
                ? testMutation.data?.message ?? 'Test failed'
                : 'Test Connection'}
        </button>
      )}

      {/* Continue */}
      <button
        onClick={() => onNext(provider, model, apiKey, host)}
        disabled={!canContinue}
        className={cn(
          'flex w-full items-center justify-center gap-3 rounded-xl px-6 py-4',
          'text-base font-semibold text-white',
          'transition-all duration-150 active:scale-[0.98]',
          'focus:outline-none focus:ring-2 focus:ring-blue-400',
          'disabled:cursor-not-allowed disabled:opacity-40',
          canContinue ? 'bg-blue-600 hover:bg-blue-500' : 'bg-gray-700',
        )}
      >
        Continue
        <ArrowRight className="h-5 w-5" />
      </button>
    </div>
  );
}
