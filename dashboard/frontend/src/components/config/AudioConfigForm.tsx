/**
 * AudioConfigForm — audio encoding and push server settings.
 */

import { errorForField } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import type { AudioConfig, AudioPushConfig, ConfigValidationError } from '@/types/config';

export interface AudioConfigFormProps {
  audio: AudioConfig;
  audioPush: AudioPushConfig;
  onAudioChange: (value: AudioConfig) => void;
  onAudioPushChange: (value: AudioPushConfig) => void;
  errors: ConfigValidationError[];
}

/** Common camera backchannel codec presets. */
const CODEC_PRESETS = [
  { value: 'pcm_mulaw', label: 'G.711 μ-law (pcm_mulaw) — Reolink CX410' },
  { value: 'pcm_alaw', label: 'G.711 A-law (pcm_alaw) — some Hikvision' },
  { value: 'aac', label: 'AAC' },
  { value: 'opus', label: 'Opus' },
];

/**
 * Audio codec and push server configuration form.
 */
export function AudioConfigForm({
  audio,
  audioPush,
  onAudioChange,
  onAudioPushChange,
  errors,
}: AudioConfigFormProps) {
  return (
    <div className="space-y-5">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Audio encoding must match your camera's backchannel codec. Reolink
        cameras typically use G.711 μ-law at 8000 Hz mono.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field label="Codec" error={errorForField(errors, 'audio.codec')}>
          <select
            value={audio.codec}
            onChange={(e) => onAudioChange({ ...audio, codec: e.target.value })}
            className={inputCls(!!errorForField(errors, 'audio.codec'))}
          >
            {CODEC_PRESETS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Sample Rate (Hz)">
          <input
            type="number"
            value={audio.sample_rate}
            onChange={(e) =>
              onAudioChange({ ...audio, sample_rate: Number(e.target.value) })
            }
            min={8000}
            step={8000}
            className={inputCls(false)}
          />
        </Field>
        <Field label="Channels">
          <select
            value={audio.channels}
            onChange={(e) =>
              onAudioChange({ ...audio, channels: Number(e.target.value) })
            }
            className={inputCls(false)}
          >
            <option value={1}>1 (Mono)</option>
            <option value={2}>2 (Stereo)</option>
          </select>
        </Field>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field
          label="Audio Push Serve Port"
          error={errorForField(errors, 'audio_push.serve_port')}
          hint="Port for the temporary HTTP server go2rtc fetches audio from"
        >
          <input
            type="number"
            value={audioPush.serve_port}
            onChange={(e) =>
              onAudioPushChange({ serve_port: Number(e.target.value) })
            }
            min={1024}
            max={65535}
            className={inputCls(!!errorForField(errors, 'audio_push.serve_port'))}
          />
        </Field>
      </div>
    </div>
  );
}
