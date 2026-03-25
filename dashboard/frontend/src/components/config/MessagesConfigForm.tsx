/**
 * MessagesConfigForm — deterrent message template editor.
 *
 * Each message field uses a <textarea> so operators can craft multi-sentence
 * warnings. Character counts are shown to help calibrate TTS duration.
 */

import { errorForField } from '@/utils/validators';
import { cn } from '@/utils/cn';
import { Field } from '@/components/common/FormField';
import type { MessagesConfig, ConfigValidationError } from '@/types/config';

export interface MessagesConfigFormProps {
  value: MessagesConfig;
  onChange: (value: MessagesConfig) => void;
  errors: ConfigValidationError[];
}

const FIELDS: Array<{
  key: keyof MessagesConfig;
  label: string;
  hint: string;
}> = [
  {
    key: 'stage1',
    label: 'Stage 1 Message',
    hint: 'Played immediately on detection — no AI needed',
  },
  {
    key: 'stage2_prefix',
    label: 'Stage 2 Prefix',
    hint: 'Spoken before the AI-generated description',
  },
  {
    key: 'stage2_suffix',
    label: 'Stage 2 Suffix',
    hint: 'Spoken after the AI-generated description',
  },
  {
    key: 'stage3_prefix',
    label: 'Stage 3 Prefix',
    hint: 'Spoken before the AI behavioural analysis',
  },
  {
    key: 'stage3_suffix',
    label: 'Stage 3 Suffix',
    hint: 'Spoken after the AI behavioural analysis',
  },
];

/**
 * Deterrent message template text editor.
 */
export function MessagesConfigForm({
  value,
  onChange,
  errors,
}: MessagesConfigFormProps) {
  const set = (k: keyof MessagesConfig, v: string) =>
    onChange({ ...value, [k]: v });

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Messages are pre-synthesized by the TTS engine and cached on disk.
        Changes here require a TTS re-render on next startup.
      </p>
      {FIELDS.map(({ key, label, hint }) => {
        const text = value[key];
        const error = errorForField(errors, `messages.${key}`);
        return (
          <Field key={key} label={label} error={error} hint={hint}>
            <div className="relative">
              <textarea
                value={text}
                onChange={(e) => set(key, e.target.value)}
                rows={3}
                className={cn(
                  'w-full resize-y rounded-lg border px-3 py-2 text-sm',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500',
                  'dark:bg-gray-800 dark:text-gray-100',
                  error
                    ? 'border-red-400 focus:border-red-400 focus:ring-red-400 dark:border-red-600'
                    : 'border-gray-300 focus:border-blue-500 dark:border-gray-600',
                )}
              />
              <span className="absolute bottom-2 right-2 text-xs text-gray-400">
                {(text ?? '').length} chars
              </span>
            </div>
          </Field>
        );
      })}
    </div>
  );
}
