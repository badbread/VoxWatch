/**
 * AiConfigForm — AI vision provider config with provider/model dropdowns
 * and estimated cost per detection.
 */

import { useState } from 'react';
import { DollarSign, ChevronDown, ChevronUp, Zap, Server, CheckCircle, XCircle, Loader, FlaskConical } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { errorForField } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import { cn } from '@/utils/cn';
import { testAiProvider } from '@/api/status';
import type { AiConfig, ConfigValidationError } from '@/types/config';

export interface AiConfigFormProps {
  value: AiConfig;
  onChange: (value: AiConfig) => void;
  errors: ConfigValidationError[];
}

/** Per-model metadata for provider dropdowns. */
interface ModelInfo {
  id: string;
  name: string;
  desc: string;
  /** Estimated cost per detection in USD (both stages combined). */
  costPerDetection: number;
  /** Whether this is the recommended default for its provider. */
  recommended?: boolean;
  /** Whether this model supports video input (not just images). */
  supportsVideo?: boolean;
}

interface ProviderInfo {
  id: string;
  name: string;
  icon: string;
  /** Whether this provider requires an API key. */
  needsApiKey: boolean;
  /** Whether this provider needs a host URL (self-hosted). */
  needsHost: boolean;
  /** Default host URL if self-hosted. */
  defaultHost?: string;
  models: ModelInfo[];
}

/** All supported AI vision providers and their models. */
const PROVIDERS: ProviderInfo[] = [
  {
    id: 'gemini',
    name: 'Google Gemini',
    icon: '🔮',
    needsApiKey: true,
    needsHost: false,
    models: [
      { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash', desc: 'Fast, cheap, multi-image + video. Best default.', costPerDetection: 0.001, recommended: true, supportsVideo: true },
      { id: 'gemini-2.0-flash-lite', name: 'Gemini 2.0 Flash Lite', desc: 'Ultra-cheap. Slightly less accurate.', costPerDetection: 0.0003, supportsVideo: true },
      { id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash', desc: 'Previous gen. Reliable and fast.', costPerDetection: 0.0008, supportsVideo: true },
      { id: 'gemini-1.5-pro', name: 'Gemini 1.5 Pro', desc: 'More accurate, slower, 10x cost.', costPerDetection: 0.01, supportsVideo: true },
      { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro', desc: 'Latest pro model. Best accuracy, highest cost.', costPerDetection: 0.015, supportsVideo: true },
    ],
  },
  {
    id: 'openai',
    name: 'OpenAI',
    icon: '🤖',
    needsApiKey: true,
    needsHost: false,
    models: [
      { id: 'gpt-4o-mini', name: 'GPT-4o Mini', desc: 'Fast and affordable. Good for most detections.', costPerDetection: 0.002, recommended: true, supportsVideo: false },
      { id: 'gpt-4o', name: 'GPT-4o', desc: 'Most capable. Higher cost, better descriptions.', costPerDetection: 0.012, supportsVideo: false },
      { id: 'gpt-4-turbo', name: 'GPT-4 Turbo', desc: 'Previous gen. Reliable but expensive.', costPerDetection: 0.025, supportsVideo: false },
      { id: 'o4-mini', name: 'o4-mini', desc: 'Reasoning model. Slower but very detailed analysis.', costPerDetection: 0.008, supportsVideo: false },
    ],
  },
  {
    id: 'anthropic',
    name: 'Anthropic Claude',
    icon: '🧠',
    needsApiKey: true,
    needsHost: false,
    models: [
      { id: 'claude-haiku-4-5', name: 'Claude Haiku 4.5', desc: 'Fast and cheap. Good for quick descriptions.', costPerDetection: 0.003, recommended: true, supportsVideo: false },
      { id: 'claude-sonnet-4-6', name: 'Claude Sonnet 4.6', desc: 'Excellent analysis. Best descriptions, higher cost.', costPerDetection: 0.015, supportsVideo: false },
    ],
  },
  {
    id: 'grok',
    name: 'xAI Grok',
    icon: '⚡',
    needsApiKey: true,
    needsHost: false,
    models: [
      { id: 'grok-2-vision-1212', name: 'Grok 2 Vision', desc: 'Fast vision model. Competitive pricing.', costPerDetection: 0.005, recommended: true, supportsVideo: false },
      { id: 'grok-2-vision-mini', name: 'Grok 2 Vision Mini', desc: 'Lighter variant. Lower cost.', costPerDetection: 0.002, supportsVideo: false },
    ],
  },
  {
    id: 'ollama',
    name: 'Ollama (Local)',
    icon: '🏠',
    needsApiKey: false,
    needsHost: true,
    defaultHost: 'http://localhost:11434',
    models: [
      { id: 'llava:7b', name: 'LLaVA 7B', desc: 'Good balance of speed and quality. 4GB VRAM.', costPerDetection: 0, recommended: true, supportsVideo: false },
      { id: 'llava:13b', name: 'LLaVA 13B', desc: 'Better accuracy. 8GB VRAM required.', costPerDetection: 0, supportsVideo: false },
      { id: 'llava:34b', name: 'LLaVA 34B', desc: 'Best local accuracy. 20GB+ VRAM.', costPerDetection: 0, supportsVideo: false },
      { id: 'bakllava', name: 'BakLLaVA', desc: 'Alternative vision model. Good at descriptions.', costPerDetection: 0, supportsVideo: false },
      { id: 'llava-phi3', name: 'LLaVA Phi-3', desc: 'Lightweight. Fast on CPU. Lower accuracy.', costPerDetection: 0, supportsVideo: false },
      { id: 'moondream', name: 'Moondream', desc: 'Tiny vision model. Very fast, basic descriptions.', costPerDetection: 0, supportsVideo: false },
    ],
  },
  {
    id: 'custom',
    name: 'Custom / OpenAI-Compatible',
    icon: '🔧',
    needsApiKey: true,
    needsHost: true,
    defaultHost: 'http://localhost:8080/v1',
    models: [
      { id: 'custom', name: 'Custom Model', desc: 'Enter model name manually below.', costPerDetection: 0, supportsVideo: false },
    ],
  },
];

/** Format cost as human-readable string. */
function formatCost(cost: number): string {
  if (cost === 0) return 'Free (local)';
  if (cost < 0.001) return `~$${(cost * 1000).toFixed(1)}/1K detections`;
  if (cost < 0.01) return `~$${(cost * 100).toFixed(1)}/100 det.`;
  return `~$${cost.toFixed(3)}/detection`;
}

/** Get cost color class based on price. */
function costColor(cost: number): string {
  if (cost === 0) return 'text-green-600 dark:text-green-400';
  if (cost < 0.003) return 'text-emerald-600 dark:text-emerald-400';
  if (cost < 0.01) return 'text-amber-600 dark:text-amber-400';
  return 'text-rose-600 dark:text-rose-400';
}

/**
 * Provider/model selector block used for both primary and fallback.
 */
function ProviderSelector({
  label,
  sublabel,
  icon: SectionIcon,
  provider,
  model,
  apiKey,
  host,
  timeout,
  onModelChange,
  onBatchChange,
  onApiKeyChange,
  onHostChange,
  onTimeoutChange,
  errors,
  errorPrefix,
}: {
  label: string;
  sublabel: string;
  icon: typeof Zap;
  provider: string;
  model: string;
  apiKey?: string;
  host?: string;
  timeout: number;
  onModelChange: (v: string) => void;
  /** Batch update provider + model + host in a single state change. */
  onBatchChange: (patch: Record<string, string>) => void;
  onApiKeyChange?: (v: string) => void;
  onHostChange?: (v: string) => void;
  onTimeoutChange: (v: number) => void;
  errors: ConfigValidationError[];
  errorPrefix: string;
}) {
  const [customModel, setCustomModel] = useState('');

  const testMutation = useMutation({
    mutationFn: testAiProvider,
  });

  const handleTest = () => {
    testMutation.mutate({
      provider,
      model,
      ...(apiKey ? { api_key: apiKey } : {}),
      ...(host ? { host } : {}),
    });
  };

  const providerInfo = PROVIDERS.find((p) => p.id === provider);
  const modelInfo = providerInfo?.models.find((m) => m.id === model);
  const isCustomModel = provider === 'custom' || (providerInfo && !modelInfo);

  const handleProviderSwitch = (newProvider: string) => {
    const newProviderInfo = PROVIDERS.find((p) => p.id === newProvider);
    const defaultModel = newProviderInfo?.models.find((m) => m.recommended) ?? newProviderInfo?.models[0];
    // Batch all changes into a single state update to avoid stale closure issues.
    // Calling onProviderChange + onModelChange separately causes the second call
    // to use a stale value object, overwriting the first change.
    const patch: Record<string, string> = { provider: newProvider };
    if (defaultModel) patch.model = defaultModel.id;
    if (newProviderInfo?.needsHost) {
      patch.host = newProviderInfo.defaultHost ?? '';
    }
    onBatchChange(patch);
  };

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <SectionIcon className="h-4 w-4 text-blue-500" />
        <h4 className="text-sm font-semibold text-gray-800 dark:text-gray-200">{label}</h4>
        <span className="text-xs text-gray-400 dark:text-gray-500">{sublabel}</span>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* Provider dropdown */}
        <Field label="Provider" error={errorForField(errors, `${errorPrefix}.provider`)}>
          <select
            value={provider}
            onChange={(e) => handleProviderSwitch(e.target.value)}
            className={inputCls(!!errorForField(errors, `${errorPrefix}.provider`))}
          >
            {PROVIDERS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.icon} {p.name}
              </option>
            ))}
          </select>
        </Field>

        {/* Model dropdown */}
        <Field label="Model" error={errorForField(errors, `${errorPrefix}.model`)}>
          {isCustomModel ? (
            <input
              type="text"
              value={model === 'custom' ? customModel : model}
              onChange={(e) => {
                setCustomModel(e.target.value);
                onModelChange(e.target.value);
              }}
              placeholder="Enter model name..."
              className={inputCls(!!errorForField(errors, `${errorPrefix}.model`))}
            />
          ) : (
            <select
              value={model}
              onChange={(e) => onModelChange(e.target.value)}
              className={inputCls(!!errorForField(errors, `${errorPrefix}.model`))}
            >
              {providerInfo?.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}{m.recommended ? ' (Recommended)' : ''}
                </option>
              ))}
            </select>
          )}
        </Field>

        {/* Model info card */}
        {modelInfo && (
          <div className="sm:col-span-2 flex items-center gap-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-700/50 dark:bg-gray-800/50">
            <div className="flex-1">
              <p className="text-xs text-gray-600 dark:text-gray-400">
                {modelInfo.desc}
              </p>
              <div className="mt-1 flex items-center gap-3 text-xs">
                {modelInfo.supportsVideo && (
                  <span className="rounded bg-purple-100 px-1.5 py-0.5 font-medium text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">
                    Video
                  </span>
                )}
                <span className="rounded bg-blue-100 px-1.5 py-0.5 font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                  Images
                </span>
              </div>
            </div>
            <div className="text-right">
              <div className={cn('text-sm font-semibold', costColor(modelInfo.costPerDetection))}>
                <DollarSign className="mr-0.5 inline h-3.5 w-3.5" />
                {formatCost(modelInfo.costPerDetection)}
              </div>
            </div>
          </div>
        )}

        {/* API Key (cloud providers) */}
        {providerInfo?.needsApiKey && onApiKeyChange && (
          <Field
            label="API Key"
            error={errorForField(errors, `${errorPrefix}.api_key`)}
            hint="Use ${ENV_VAR} syntax to reference environment variables"
            className="sm:col-span-2"
          >
            <input
              type="password"
              value={apiKey ?? ''}
              onChange={(e) => onApiKeyChange(e.target.value)}
              placeholder={`\${${provider.toUpperCase()}_API_KEY}`}
              autoComplete="off"
              className={inputCls(!!errorForField(errors, `${errorPrefix}.api_key`))}
            />
          </Field>
        )}

        {/* Host URL (self-hosted providers) */}
        {providerInfo?.needsHost && onHostChange && (
          <Field label="Host URL" className="sm:col-span-2">
            <input
              type="url"
              value={host ?? ''}
              onChange={(e) => onHostChange(e.target.value)}
              placeholder={providerInfo.defaultHost ?? 'http://localhost:11434'}
              className={inputCls(false)}
            />
          </Field>
        )}

        {/* Timeout */}
        <Field
          label="Timeout (seconds)"
          error={errorForField(errors, `${errorPrefix}.timeout_seconds`)}
        >
          <input
            type="number"
            value={timeout}
            onChange={(e) => onTimeoutChange(Number(e.target.value))}
            min={1}
            max={120}
            className={inputCls(!!errorForField(errors, `${errorPrefix}.timeout_seconds`))}
          />
        </Field>

        {/* Test Connection Button */}
        <div className="sm:col-span-2">
          <button
            type="button"
            onClick={handleTest}
            disabled={testMutation.isPending || (!apiKey && providerInfo?.needsApiKey)}
            className={cn(
              'flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-all',
              'active:scale-[0.98]',
              'focus:outline-none focus:ring-2 focus:ring-blue-500',
              'disabled:cursor-not-allowed disabled:opacity-50',
              testMutation.isSuccess && testMutation.data?.success
                ? 'border-2 border-green-500 bg-green-50 text-green-700 dark:bg-green-950/20 dark:text-green-300'
                : testMutation.isSuccess && !testMutation.data?.success
                  ? 'border-2 border-red-500 bg-red-50 text-red-700 dark:bg-red-950/20 dark:text-red-300'
                  : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700',
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
        </div>
      </div>
    </div>
  );
}

/**
 * AI provider configuration for primary and fallback models with cost estimates.
 */
export function AiConfigForm({ value, onChange, errors }: AiConfigFormProps) {
  const [showCostBreakdown, setShowCostBreakdown] = useState(false);

  const setPrimary = (patch: Partial<AiConfig['primary']>) =>
    onChange({ ...value, primary: { ...value.primary, ...patch } });
  const setFallback = (patch: Partial<AiConfig['fallback']>) =>
    onChange({ ...value, fallback: { ...value.fallback, ...patch } });

  // Cost estimation
  const primaryProvider = PROVIDERS.find((p) => p.id === value.primary.provider);
  const primaryModel = primaryProvider?.models.find((m) => m.id === value.primary.model);
  const costPerDetection = primaryModel?.costPerDetection ?? 0;
  const estimatedDailyCost10 = costPerDetection * 10;
  const estimatedDailyCost50 = costPerDetection * 50;
  const estimatedMonthlyCost = costPerDetection * 30 * 30; // 30 detections/day * 30 days

  return (
    <div className="space-y-6">
      {/* Cost estimate banner */}
      <div className="rounded-xl border border-gray-200 bg-gradient-to-r from-gray-50 to-blue-50 dark:border-gray-700/50 dark:from-gray-800/50 dark:to-blue-950/20">
        <div className="px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <DollarSign className="h-4 w-4 text-emerald-500" />
              <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                Estimated Cost
              </span>
            </div>
            <div className={cn('text-lg font-bold', costColor(costPerDetection))}>
              {costPerDetection === 0 ? 'Free' : `~$${estimatedMonthlyCost.toFixed(2)}/mo`}
            </div>
          </div>
          {costPerDetection > 0 && (
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Based on ~30 detections/day with {primaryModel?.name ?? value.primary.model}
            </p>
          )}
        </div>

        <button
          onClick={() => setShowCostBreakdown(!showCostBreakdown)}
          className="flex w-full items-center justify-between border-t border-gray-200 px-4 py-2 text-xs font-medium text-gray-500 hover:bg-gray-100/50 dark:border-gray-700/50 dark:text-gray-400 dark:hover:bg-gray-800/30 transition-colors"
        >
          <span>Cost breakdown</span>
          {showCostBreakdown ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>

        {showCostBreakdown && (
          <div className="border-t border-gray-200 px-4 py-3 dark:border-gray-700/50">
            <div className="grid grid-cols-3 gap-3 text-center">
              <div>
                <p className="text-lg font-bold text-gray-800 dark:text-gray-200">
                  {costPerDetection === 0 ? '$0' : `$${costPerDetection.toFixed(4)}`}
                </p>
                <p className="text-xs text-gray-400">per detection</p>
              </div>
              <div>
                <p className="text-lg font-bold text-gray-800 dark:text-gray-200">
                  {costPerDetection === 0 ? '$0' : `$${estimatedDailyCost10.toFixed(3)}`}
                </p>
                <p className="text-xs text-gray-400">10 det./day</p>
              </div>
              <div>
                <p className="text-lg font-bold text-gray-800 dark:text-gray-200">
                  {costPerDetection === 0 ? '$0' : `$${estimatedDailyCost50.toFixed(2)}`}
                </p>
                <p className="text-xs text-gray-400">50 det./day</p>
              </div>
            </div>
            <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
              Estimates based on ~3 snapshots + 1 video clip per detection. Actual costs vary by image size and response length.
            </p>
          </div>
        )}
      </div>

      {/* Primary provider — passes both apiKey+onApiKeyChange AND host+onHostChange
          so the correct field is shown regardless of which provider is selected. */}
      <ProviderSelector
        label="Primary AI"
        sublabel="Cloud-based, used first"
        icon={Zap}
        provider={value.primary.provider}
        model={value.primary.model}
        {...(value.primary.api_key != null ? { apiKey: value.primary.api_key } : {})}
        {...(value.primary.host != null ? { host: value.primary.host } : {})}
        timeout={value.primary.timeout_seconds}
        onModelChange={(v) => setPrimary({ model: v })}
        onBatchChange={(patch) => setPrimary(patch as Partial<AiConfig['primary']>)}
        onApiKeyChange={(v) => setPrimary({ api_key: v })}
        onHostChange={(v) => setPrimary({ host: v })}
        onTimeoutChange={(v) => setPrimary({ timeout_seconds: v })}
        errors={errors}
        errorPrefix="ai.primary"
      />

      <hr className="border-gray-200 dark:border-gray-700" />

      {/* Fallback provider — same treatment: both credential props wired up
          so switching fallback to a cloud provider shows the API key field. */}
      <ProviderSelector
        label="Fallback AI"
        sublabel="Used when primary fails"
        icon={Server}
        provider={value.fallback.provider}
        model={value.fallback.model}
        {...(value.fallback.api_key != null ? { apiKey: value.fallback.api_key } : {})}
        {...(value.fallback.host != null ? { host: value.fallback.host } : {})}
        timeout={value.fallback.timeout_seconds}
        onModelChange={(v) => setFallback({ model: v })}
        onBatchChange={(patch) => setFallback(patch as Partial<AiConfig['fallback']>)}
        onApiKeyChange={(v) => setFallback({ api_key: v })}
        onHostChange={(v) => setFallback({ host: v })}
        onTimeoutChange={(v) => setFallback({ timeout_seconds: v })}
        errors={errors}
        errorPrefix="ai.fallback"
      />
    </div>
  );
}
