/**
 * AiConfigForm — AI vision provider config with provider/model dropdowns
 * and estimated cost per detection.
 *
 * Layout is compact: provider + model on one row, description/badges/cost
 * on a single info line beneath, and API key + timeout sharing a row.
 * A small monthly-estimate footer sits at the very bottom of the section.
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
      { id: 'gemini-3.1-flash', name: 'Gemini 3.1 Flash', desc: 'Fast, cheap, multi-image + video. Best default.', costPerDetection: 0.001, recommended: true, supportsVideo: true },
      { id: 'gemini-3.1-flash-lite', name: 'Gemini 3.1 Flash Lite', desc: 'Ultra-cheap. Great for high-volume deployments.', costPerDetection: 0.0003, supportsVideo: true },
      { id: 'gemini-3.1-pro', name: 'Gemini 3.1 Pro', desc: 'Most accurate. Best descriptions, higher cost.', costPerDetection: 0.01, supportsVideo: true },
      { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash', desc: 'Previous gen. Still reliable and fast.', costPerDetection: 0.001, supportsVideo: true },
      { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro', desc: 'Previous gen pro. Good accuracy.', costPerDetection: 0.008, supportsVideo: true },
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

/** Format cost as a compact per-100-detections string for the inline info row. */
function formatCostCompact(cost: number): string {
  if (cost === 0) return 'Free';
  if (cost < 0.001) return `~$${(cost * 1000).toFixed(1)}/1K`;
  if (cost < 0.01) return `~$${(cost * 100).toFixed(1)}/100`;
  return `~$${cost.toFixed(3)}/det`;
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
 * Compact layout: dropdowns on one row, info line beneath, API key + timeout
 * sharing a row (stacked on mobile), then the test button.
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
    <div className="space-y-2">
      {/* Section header */}
      <div className="flex items-center gap-2">
        <SectionIcon className="h-3.5 w-3.5 text-blue-500 shrink-0" />
        <h4 className="text-xs font-semibold text-gray-800 dark:text-gray-200">{label}</h4>
        <span className="text-[11px] text-gray-400 dark:text-gray-500">{sublabel}</span>
      </div>

      {/* Provider + Model on one row */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
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
      </div>

      {/* Inline model info: description · badges · cost — all on one line */}
      {modelInfo && (
        <div className="flex items-center justify-between gap-2 px-0.5">
          <span className="truncate text-xs text-gray-500 dark:text-gray-400">
            {modelInfo.desc}
          </span>
          <div className="flex shrink-0 items-center gap-1.5">
            {modelInfo.supportsVideo && (
              <span className="rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">
                Video
              </span>
            )}
            <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
              Images
            </span>
            <span className={cn('font-mono text-xs font-medium', costColor(modelInfo.costPerDetection))}>
              {formatCostCompact(modelInfo.costPerDetection)}
            </span>
          </div>
        </div>
      )}

      {/* Host URL (self-hosted providers) */}
      {providerInfo?.needsHost && onHostChange && (
        <Field label="Host URL">
          <input
            type="url"
            value={host ?? ''}
            onChange={(e) => onHostChange(e.target.value)}
            placeholder={providerInfo.defaultHost ?? 'http://localhost:11434'}
            className={inputCls(false)}
          />
        </Field>
      )}

      {/* API Key + Timeout on the same row (stacked on mobile) */}
      {providerInfo?.needsApiKey && onApiKeyChange && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto]">
          <Field
            label="API Key"
            error={errorForField(errors, `${errorPrefix}.api_key`)}
            hint="Use ${ENV_VAR} syntax to reference environment variables"
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

          <div className="w-full sm:w-24">
            <Field
              label="Timeout (s)"
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
          </div>
        </div>
      )}

      {/* Timeout-only row for providers that don't need an API key (e.g. Ollama) */}
      {!providerInfo?.needsApiKey && (
        <div className="w-full sm:w-32">
          <Field
            label="Timeout (s)"
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
        </div>
      )}

      {/* Test Connection button */}
      <button
        type="button"
        onClick={handleTest}
        disabled={testMutation.isPending || (!apiKey && providerInfo?.needsApiKey)}
        className={cn(
          'flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all',
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
  );
}

/**
 * AI provider configuration for primary and fallback models with cost estimates.
 *
 * The big cost card has been replaced by a compact footer line at the bottom.
 * A small collapsible breakdown remains for users who want the detail.
 */
export function AiConfigForm({ value, onChange, errors }: AiConfigFormProps) {
  const [showCostBreakdown, setShowCostBreakdown] = useState(false);

  const setPrimary = (patch: Partial<AiConfig['primary']>) =>
    onChange({ ...value, primary: { ...value.primary, ...patch } });
  const setFallback = (patch: Partial<AiConfig['fallback']>) =>
    onChange({ ...value, fallback: { ...value.fallback, ...patch } });

  // Cost estimation (primary provider drives the footer estimate)
  const primaryProvider = PROVIDERS.find((p) => p.id === value.primary.provider);
  const primaryModel = primaryProvider?.models.find((m) => m.id === value.primary.model);
  const costPerDetection = primaryModel?.costPerDetection ?? 0;
  const estimatedDailyCost10 = costPerDetection * 10;
  const estimatedDailyCost50 = costPerDetection * 50;
  const estimatedMonthlyCost = costPerDetection * 30 * 30; // 30 detections/day * 30 days

  return (
    <div className="space-y-4">
      {/* Primary provider */}
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

      {/* Fallback provider */}
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

      {/* Monthly cost footer — compact, replaces the old top banner card */}
      <div className="border-t border-gray-200 pt-2 dark:border-gray-700">
        {/* Collapsible cost breakdown */}
        <button
          type="button"
          onClick={() => setShowCostBreakdown(!showCostBreakdown)}
          className="flex w-full items-center justify-between text-[10px] font-medium text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 transition-colors"
        >
          <span>Cost breakdown</span>
          {showCostBreakdown ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>

        {showCostBreakdown && (
          <div className="mt-2 grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                {costPerDetection === 0 ? '$0' : `$${costPerDetection.toFixed(4)}`}
              </p>
              <p className="text-[10px] text-gray-400">per detection</p>
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                {costPerDetection === 0 ? '$0' : `$${estimatedDailyCost10.toFixed(3)}`}
              </p>
              <p className="text-[10px] text-gray-400">10 det./day</p>
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                {costPerDetection === 0 ? '$0' : `$${estimatedDailyCost50.toFixed(2)}`}
              </p>
              <p className="text-[10px] text-gray-400">50 det./day</p>
            </div>
            <p className="col-span-3 text-[10px] text-gray-400 dark:text-gray-500">
              Estimates based on ~3 snapshots + 1 video clip per detection. Actual costs vary.
            </p>
          </div>
        )}

        {/* Always-visible monthly estimate line */}
        <div className="mt-1.5 flex items-center justify-end gap-1 text-[11px] text-gray-400 dark:text-gray-500">
          <DollarSign className="h-3 w-3 text-emerald-500" />
          <span>
            {costPerDetection === 0
              ? 'Free · local model'
              : `~$${estimatedMonthlyCost.toFixed(2)}/mo estimated · 30 detections/day · ${primaryModel?.name ?? value.primary.model}`}
          </span>
        </div>
      </div>
    </div>
  );
}
