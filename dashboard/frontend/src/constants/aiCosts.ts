/**
 * aiCosts — shared AI model cost constants and formatting helpers.
 *
 * All cost values are estimated USD per detection event (combining image
 * snapshots + video clip tokens for a typical deterrent trigger).
 * Used in CameraStatusCard and ServiceStatusCard to keep figures in sync.
 */

/**
 * Estimated cost per detection, keyed as "provider:model".
 * Zero means free (local inference). Null means unknown/unlisted.
 */
export const COST_MAP: Record<string, number> = {
  'gemini:gemini-2.0-flash': 0.001,
  'gemini:gemini-2.0-flash-lite': 0.0003,
  'gemini:gemini-1.5-flash': 0.0008,
  'gemini:gemini-1.5-pro': 0.01,
  'gemini:gemini-2.5-pro': 0.015,
  'openai:gpt-4o-mini': 0.002,
  'openai:gpt-4o': 0.012,
  'openai:gpt-4-turbo': 0.025,
  'anthropic:claude-haiku-4-5': 0.003,
  'anthropic:claude-sonnet-4-6': 0.015,
  'grok:grok-2-vision-1212': 0.005,
  'grok:grok-2-vision-mini': 0.002,
  'ollama:llava:7b': 0,
};

/**
 * Format a cost value as a human-readable string suitable for display in
 * a status card or config form. Returns "Free (local)" for zero-cost models.
 */
export function formatCost(cost: number): string {
  if (cost === 0) return 'Free (local)';
  if (cost < 0.001) return `~$${(cost * 1000).toFixed(1)}/1K detections`;
  if (cost < 0.01) return `~$${(cost * 100).toFixed(1)}/100 det.`;
  return `~$${cost.toFixed(3)}/detection`;
}

/**
 * Return a Tailwind text-color class for a cost value.
 * Green = free/very cheap, escalating through amber to rose for expensive models.
 */
export function costColor(cost: number): string {
  if (cost === 0) return 'text-green-600 dark:text-green-400';
  if (cost < 0.003) return 'text-emerald-600 dark:text-emerald-400';
  if (cost < 0.01) return 'text-amber-600 dark:text-amber-400';
  return 'text-rose-600 dark:text-rose-400';
}
