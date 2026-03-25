/**
 * Client-side configuration validation for the VoxWatch config editor.
 *
 * Validation runs on blur in each form section and on clicking "Save". The
 * backend performs its own authoritative validation; these checks are purely
 * for fast UX feedback before the network round-trip.
 */

import type {
  VoxWatchConfig,
  ConfigValidationResult,
  ConfigValidationError,
} from '@/types/config';

// ---------------------------------------------------------------------------
// Primitive validators
// ---------------------------------------------------------------------------

function requireString(
  errors: ConfigValidationError[],
  field: string,
  value: unknown,
  label: string,
): void {
  if (typeof value !== 'string' || value.trim() === '') {
    errors.push({ field, message: `${label} is required.` });
  }
}

function requirePort(
  errors: ConfigValidationError[],
  field: string,
  value: unknown,
  label: string,
): void {
  const n = Number(value);
  if (!Number.isInteger(n) || n < 1 || n > 65535) {
    errors.push({
      field,
      message: `${label} must be an integer between 1 and 65535.`,
    });
  }
}

function requirePositiveNumber(
  errors: ConfigValidationError[],
  field: string,
  value: unknown,
  label: string,
): void {
  const n = Number(value);
  if (isNaN(n) || n <= 0) {
    errors.push({ field, message: `${label} must be a positive number.` });
  }
}

function requireRange(
  errors: ConfigValidationError[],
  field: string,
  value: unknown,
  label: string,
  min: number,
  max: number,
): void {
  const n = Number(value);
  if (isNaN(n) || n < min || n > max) {
    errors.push({
      field,
      message: `${label} must be between ${min} and ${max}.`,
    });
  }
}

// ---------------------------------------------------------------------------
// Section validators
// ---------------------------------------------------------------------------

function validateFrigate(
  cfg: VoxWatchConfig,
  errors: ConfigValidationError[],
): void {
  requireString(errors, 'frigate.host', cfg.frigate.host, 'Frigate host');
  requirePort(errors, 'frigate.port', cfg.frigate.port, 'Frigate port');
  requireString(
    errors,
    'frigate.mqtt_host',
    cfg.frigate.mqtt_host,
    'MQTT host',
  );
  requirePort(
    errors,
    'frigate.mqtt_port',
    cfg.frigate.mqtt_port,
    'MQTT port',
  );
  requireString(
    errors,
    'frigate.mqtt_topic',
    cfg.frigate.mqtt_topic,
    'MQTT topic',
  );
}

function validateGo2rtc(
  cfg: VoxWatchConfig,
  errors: ConfigValidationError[],
): void {
  requireString(errors, 'go2rtc.host', cfg.go2rtc.host, 'go2rtc host');
  requirePort(
    errors,
    'go2rtc.api_port',
    cfg.go2rtc.api_port,
    'go2rtc API port',
  );
}

function validateCameras(
  cfg: VoxWatchConfig,
  errors: ConfigValidationError[],
): void {
  const keys = Object.keys(cfg.cameras);
  if (keys.length === 0) {
    errors.push({
      field: 'cameras',
      message: 'At least one camera must be configured.',
    });
    return;
  }
  for (const key of keys) {
    const cam = cfg.cameras[key];
    if (!cam) continue;
    requireString(
      errors,
      `cameras.${key}.go2rtc_stream`,
      cam.go2rtc_stream,
      `Camera "${key}" go2rtc stream`,
    );
  }
}

function validateConditions(
  cfg: VoxWatchConfig,
  errors: ConfigValidationError[],
): void {
  requireRange(
    errors,
    'conditions.min_score',
    cfg.conditions.min_score,
    'Minimum score',
    0.0,
    1.0,
  );
  requirePositiveNumber(
    errors,
    'conditions.cooldown_seconds',
    cfg.conditions.cooldown_seconds,
    'Cooldown seconds',
  );

  const { mode } = cfg.conditions.active_hours;
  if (!['always', 'sunset_sunrise', 'fixed'].includes(mode)) {
    errors.push({
      field: 'conditions.active_hours.mode',
      message: 'Active hours mode must be "always", "sunset_sunrise", or "fixed".',
    });
  }

  if (mode === 'fixed') {
    const timeRe = /^([01]\d|2[0-3]):[0-5]\d$/;
    if (!timeRe.test(cfg.conditions.active_hours.start)) {
      errors.push({
        field: 'conditions.active_hours.start',
        message: 'Start time must be in HH:MM format.',
      });
    }
    if (!timeRe.test(cfg.conditions.active_hours.end)) {
      errors.push({
        field: 'conditions.active_hours.end',
        message: 'End time must be in HH:MM format.',
      });
    }
  }

  if (mode === 'sunset_sunrise') {
    requireRange(
      errors,
      'conditions.latitude',
      cfg.conditions.latitude,
      'Latitude',
      -90,
      90,
    );
    requireRange(
      errors,
      'conditions.longitude',
      cfg.conditions.longitude,
      'Longitude',
      -180,
      180,
    );
  }
}

function validateAi(
  cfg: VoxWatchConfig,
  errors: ConfigValidationError[],
): void {
  requireString(
    errors,
    'ai.primary.provider',
    cfg.ai.primary.provider,
    'Primary AI provider',
  );
  requireString(
    errors,
    'ai.primary.model',
    cfg.ai.primary.model,
    'Primary AI model',
  );
  requirePositiveNumber(
    errors,
    'ai.primary.timeout_seconds',
    cfg.ai.primary.timeout_seconds,
    'Primary AI timeout',
  );
  requireString(
    errors,
    'ai.fallback.provider',
    cfg.ai.fallback.provider,
    'Fallback AI provider',
  );
  requireString(
    errors,
    'ai.fallback.model',
    cfg.ai.fallback.model,
    'Fallback AI model',
  );
  requirePositiveNumber(
    errors,
    'ai.fallback.timeout_seconds',
    cfg.ai.fallback.timeout_seconds,
    'Fallback AI timeout',
  );
}

function validateTts(
  cfg: VoxWatchConfig,
  errors: ConfigValidationError[],
): void {
  requireString(errors, 'tts.engine', cfg.tts.engine, 'TTS engine');
  requireRange(
    errors,
    'tts.voice_speed',
    cfg.tts.voice_speed,
    'Voice speed',
    0.5,
    3.0,
  );
}

function validateAudio(
  cfg: VoxWatchConfig,
  errors: ConfigValidationError[],
): void {
  requireString(errors, 'audio.codec', cfg.audio.codec, 'Audio codec');
  requirePositiveNumber(
    errors,
    'audio.sample_rate',
    cfg.audio.sample_rate,
    'Sample rate',
  );
  requirePort(
    errors,
    'audio_push.serve_port',
    cfg.audio_push.serve_port,
    'Audio push serve port',
  );
}

function validateMessages(
  cfg: VoxWatchConfig,
  errors: ConfigValidationError[],
): void {
  requireString(
    errors,
    'messages.stage1',
    cfg.messages.stage1,
    'Stage 1 message',
  );
}

function validateLogging(
  cfg: VoxWatchConfig,
  errors: ConfigValidationError[],
): void {
  const validLevels = ['DEBUG', 'INFO', 'WARNING', 'ERROR'];
  if (!validLevels.includes(cfg.logging.level)) {
    errors.push({
      field: 'logging.level',
      message: `Log level must be one of: ${validLevels.join(', ')}.`,
    });
  }
  requireString(
    errors,
    'logging.file',
    cfg.logging.file,
    'Log file path',
  );
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Validates a full VoxWatch configuration object client-side.
 *
 * Runs all section validators and returns a combined result. The backend
 * performs authoritative validation; this function is for fast UX feedback.
 *
 * @param config - The full config object from the editor forms
 * @returns A validation result with an array of errors (empty = valid)
 */
export function validateConfig(config: VoxWatchConfig): ConfigValidationResult {
  const errors: ConfigValidationError[] = [];

  validateFrigate(config, errors);
  validateGo2rtc(config, errors);
  validateCameras(config, errors);
  validateConditions(config, errors);
  validateAi(config, errors);
  validateTts(config, errors);
  validateAudio(config, errors);
  validateMessages(config, errors);
  validateLogging(config, errors);

  return { valid: errors.length === 0, errors };
}

/**
 * Returns validation errors that apply to a specific field path prefix.
 *
 * Useful for individual form sections to show only their relevant errors.
 *
 * @param errors - Full error array from validateConfig()
 * @param prefix - Dot-separated field prefix (e.g. "frigate", "conditions")
 */
export function errorsForSection(
  errors: ConfigValidationError[],
  prefix: string,
): ConfigValidationError[] {
  return errors.filter((e) => e.field.startsWith(prefix));
}

/**
 * Returns the first error message for a specific field path, or undefined.
 *
 * @param errors - Full error array from validateConfig()
 * @param field - Exact dot-separated field path (e.g. "frigate.host")
 */
export function errorForField(
  errors: ConfigValidationError[],
  field: string,
): string | undefined {
  return errors.find((e) => e.field === field)?.message;
}
