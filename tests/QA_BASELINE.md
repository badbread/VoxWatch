# VoxWatch QA Baseline Manifest
# Version: 1.7 | Date: 2026-03-29 | Coverage: All endpoints, components, and behaviors

This manifest maps EVERY testable element in the VoxWatch system. If something
is not listed here, it is not covered in QA. Update this document whenever the
codebase changes.

---

## Section 1: API Endpoints

### Authentication (all /api/* routes)

| Field | Value |
|-------|-------|
| Mechanism | HTTP Bearer token via Authorization header |
| Env var | DASHBOARD_API_KEY |
| Dev mode | If DASHBOARD_API_KEY unset, all requests pass (warning logged) |
| Comparison | hmac.compare_digest() constant-time |
| Missing header | HTTP 401 with WWW-Authenticate |
| Wrong token | HTTP 403 |

### POST /api/audio/test
- Push test audio to camera speaker via go2rtc
- Request: camera_name (required, regex validated), message (optional, max 200)
- Response: success, camera, stream_name, message
- Errors: 400 (bad name), 404 (not found), 429 (rate limit), 503 (go2rtc down)
- Behavior: warmup silence -> 2s wait -> real audio

### POST /api/audio/preview
- Generate deterrent audio preview for browser playback
- Request: persona, voice, provider, provider_host, message, speed
- Response: audio/wav streaming
- Dispatch personas proxy to VoxWatch port 8892, fallback to local TTS

### POST /api/audio/upload-intro
- Upload custom dispatch channel intro audio file (WAV/MP3)
- Request: multipart/form-data with audio file (max 10MB)
- Response: saved path, file size, detected format
- Validates audio magic bytes (RIFF, MP3, Ogg, FLAC)
- Saves atomically to /config/audio/dispatch_intro.wav

### POST /api/audio/generate-intro
- Generate dispatch intro via TTS and optionally save
- Proxies to VoxWatch Preview API for local TTS providers
- Falls back to direct cloud synthesis (ElevenLabs, OpenAI, Cartesia)
- Returns WAV bytes with X-Intro-Saved header

### POST /api/audio/announce
- Push a spoken announcement to a specific camera speaker
- Request: camera (required), message (required, max 1000 chars), voice (optional), provider (optional), speed (optional), tone (optional)
- Proxies to VoxWatch Preview API for TTS generation
- Response: success, camera, duration_ms, error
- Errors: 400 (missing camera/message, message exceeds 1000 chars)

### GET /api/audio/piper-voices
- List all known Piper voice models with installation status
- Response model: PiperVoiceListResponse { voices: list[PiperVoiceInfo], builtin_dir: str, downloaded_dir: str }
- No auth required beyond standard /api/* Bearer token

### DELETE /api/audio/piper-voices/{model_name}
- Delete a downloaded Piper voice from /data/piper-voices/
- Proxies to VoxWatch Preview API (dashboard /data mount is read-only)
- Errors: 400 (bad name), 403 (builtin), 404 (not found), 503 (Preview API down)

### POST /api/audio/test-tts-provider
- Validate cloud/local TTS provider credentials; no audio generated
- Request: provider (str), api_key (optional str)
- Providers: elevenlabs (GET /v1/user), openai (GET /v1/models), cartesia (GET /voices), kokoro (GET /voices or /v1/audio/voices)
- Kokoro: api_key field repurposed to send host URL; falls back to config
- Always returns HTTP 200; ok field indicates pass/fail

### GET /api/cameras
- List all cameras (config + Frigate + go2rtc merged)
- Response: array of CameraStatus

### GET /api/cameras/{name}
- Single camera details; name validated against ^[a-zA-Z0-9_-]+$
- Errors: 400 (invalid chars), 404 (not found)

### GET /api/cameras/{name}/snapshot
- Proxied JPEG from Frigate
- Errors: 400, 404, 502 (Frigate down), 503

### POST /api/cameras/{name}/identify
- ONVIF WS-Security probe for camera model
- Response: identified, camera_ip, manufacturer, model, firmware, speaker_status
- UI behavior: auto-triggered on camera click in wizard (new)

### GET /api/config
- Config as JSON with secrets masked (***MASKED***)
- ${ENV_VAR} tokens preserved as-is

### GET /api/config/raw
- Config as masked YAML text

### PUT /api/config
- Validate + atomically save config
- Restores masked secrets from disk before writing
- Errors: 400 (validation), 422 (malformed)
- Bug fix: null pipeline values no longer crash validator

### POST /api/config/validate
- Dry-run validation, no file write

### GET /api/status
- Full system status: Frigate + go2rtc + cameras + last events
- Response includes voxwatch: VoxWatchServiceStatus field (read from /data/status.json)

### GET /api/status/events
- Return recent detection events from events.jsonl with full pipeline details
- Query params: limit (int 1-200, default 50), camera (string, optional filter)
- Response model: list[DetectionEvent] sorted newest-first
- Reads EVENTS_FILE; returns [] on FileNotFoundError; skips malformed JSON lines

### GET /api/system/health
- Fast in-process check (no outbound requests)

### GET /api/system/info
- Hostname, platform, Python version, paths

### GET /api/system/frigate
- Live Frigate probe

### GET /api/system/go2rtc
- Live go2rtc probe

### POST /api/system/test-ai
- Test AI provider connectivity with masked key resolution

### POST /api/system/test-tts
- Test TTS provider connectivity

### GET /api/system/logs
- Tail log file with level filtering
- Supports both console and file log formats

### POST /api/system/mqtt-simulation
- Publish synthetic Frigate event to MQTT

### GET /api/setup/status (NO AUTH)
- Check if config.yaml exists, which sections are configured
- Returns: config_exists, setup_complete, frigate_configured, mqtt_configured, ai_configured, cameras_configured, frigate_host_env
- Pre-fills frigate_host from FRIGATE_HOST env var
- No authentication required (first-run has no API key)

### POST /api/setup/probe (NO AUTH)
- Probes Frigate + go2rtc + MQTT concurrently from provided host
- Tries Frigate on ports 5000, 5001, 8971
- Returns: cameras found, versions, backchannel info, MQTT reachability
- 409 Conflict if config.yaml already exists
- Input validation: host must match ^[a-zA-Z0-9._-]+$

### POST /api/setup/generate-config (NO AUTH)
- Builds and atomically writes config.yaml from wizard inputs
- 409 Conflict if config.yaml already exists
- Includes: frigate, go2rtc, mqtt, ai, tts, response_mode, cameras sections
- Atomic write via tempfile + os.replace

### POST /api/setup/test-frigate (NO AUTH)
- Test Frigate connectivity from wizard before config is written
- Request: host (string), port (integer)
- Response: ok (bool), message (string), version (string), latency_ms (float)
- Errors: connection refused, timeout, unexpected HTTP status

### POST /api/setup/test-mqtt (NO AUTH)
- Test MQTT broker connectivity with optional credentials from wizard
- Request: host (string), port (integer), username (string, optional), password (string, optional)
- Response: ok (bool), message (string), latency_ms (float)
- Tests connect + subscribe roundtrip; checks auth rejection on bad credentials

### POST /api/setup/test-go2rtc (NO AUTH)
- Test go2rtc connectivity from wizard before config is written
- Request: host (string), port (integer)
- Response: ok (bool), message (string), version (string), latency_ms (float)
- Errors: connection refused, timeout, unexpected HTTP status

### POST /api/wizard/detect
- Probe camera backchannel capabilities

### POST /api/wizard/test-audio
- Generate test tone and push via go2rtc

### GET /api/wizard/serve/{filename}
- Serve wizard WAV files (path traversal protected)

### POST /api/wizard/save
- Save camera config (upsert)

---

## Section 2: Frontend Routes

| Path | Page | Description |
|------|------|-------------|
| /setup | SetupPage | Full-screen first-run wizard (no sidebar). Auto-redirect when no config.yaml |
| / | DashboardPage | System hero + camera grid + activity + quick actions |
| /cameras | CamerasPage | Camera hub with detail panel, deep-link via ?selected= |
| /config | ConfigPage | Form Editor (6 tabs) + Advanced YAML (Monaco) |
| /advanced | AdvancedPage | Formerly Tests -- 5 sections: Audio, TTS, Camera, MQTT Sim, Logs + Logging settings |
| /wizard | WizardPage | 7-step camera setup wizard |
| * | NotFoundPage | 404 |

**SetupGuard:** All routes except /setup are wrapped in SetupGuard. If config.yaml does not exist, auto-redirects to /setup.

**Setup wizard steps (9):** welcome -> frigate -> discovery -> mqtt -> ai -> tts -> response_mode -> cameras -> review

**Navigation rename:** Sidebar and mobile nav item previously labelled Tests is now labelled Advanced.

**Logging settings moved:** Log level and log file path configuration moved from Config editor (was tab 6) to the Advanced page.

---

## Section 3: Config Tabs

Current tab order (updated):

1. Personality -- Response mode picker + mood + system name + surveillance preset + operator name + guard dog names
2. TTS -- Engine selection + voice settings
3. Detection -- Active hours, cooldown, min_score
4. Pipeline -- Initial Response -> Escalation -> Resolution (prefix/suffix default cleared; Response Mode label renamed to Personality)
5. AI Provider -- Primary + fallback with test connection + Gemini model auto-selection
6. Connections -- Frigate + go2rtc + MQTT connection settings + MQTT Publishing config + test buttons for Frigate, MQTT, go2rtc

**Previous tab order (v1.1):** Services -> Mode -> AI Provider -> Pipeline -> TTS/Personality -> Logging

**Removed from Config tabs:** Logging tab removed; logging settings now live on the Advanced page.

---

## Section 4: Config Fields (key defaults)

- frigate.host: localhost, port: 5000
- go2rtc.host: localhost, api_port: 1984
- conditions.min_score: 0.7, cooldown_seconds: 60
- ai.primary: gemini-2.5-flash (auto-selected by UI), fallback: ollama/llava:7b
- tts.engine: piper, model: en_US-lessac-medium
- audio.codec: pcm_mulaw, sample_rate: 8000
- response_mode.name: private_security
- pipeline: initial_response enabled (delay 0), escalation enabled (delay 6)
- pipeline.initial_response.prefix: empty string (default cleared)
- pipeline.initial_response.suffix: empty string (default cleared)

### New Config Fields (added this session)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| response_mode.mood | string | observant | Homeowner mood: observant / friendly / firm / confrontational / threatening |
| response_mode.system_name | string | (none) | Automated surveillance system name (used by automated_surveillance mode) |
| response_mode.surveillance_preset | string | standard | Robot persona preset: standard / t800 / hal / wopr / glados |
| response_mode.operator_name | string | (none) | Live operator display name (used by live_operator mode) |
| response_mode.guard_dog.dog_names | list[string] | [] | Guard dog names (0-3 entries); used in homeowner mode templates |
| mqtt_publish.enabled | bool | true | Enable MQTT event publishing |
| mqtt_publish.topic_prefix | string | voxwatch | MQTT topic prefix for all published events |
| mqtt_publish.include_ai_analysis | bool | false | Include full AI analysis text in stage event payloads |
| mqtt_publish.include_snapshot_url | bool | false | Include Frigate snapshot URL in detection event payloads |

---

## Section 5: Service Startup & Detection Pipeline

### Service Startup
- If config.yaml missing: service polls every 5s (does NOT crash)
- Logs: Waiting for setup. Open the dashboard to configure VoxWatch.
- When config appears: loads and starts normally
- load_config_or_none() returns None instead of sys.exit

### Detection Pipeline
```
MQTT event (type=new, label=person)
  -> Guard: active_hours -> Guard: cooldown -> Guard: min_score
  -> Warmup push (concurrent with AI)
  -> Initial Response (t=0): mode-specific pre-cached message
  -> Escalation (t=6s): AI snapshot analysis + TTS
  -> Resolution (optional): Area clear when person leaves
```

### MQTT Event Publishing (new)

The service publishes structured MQTT events at each pipeline stage via voxwatch/mqtt_publisher.py.

| Event trigger | Topic pattern | Payload highlights |
|---------------|---------------|--------------------|
| Detection start | {prefix}/detection/start | camera, label, score, timestamp |
| Stage executed | {prefix}/detection/stage | camera, stage name, message, ai_analysis (if enabled), snapshot_url (if enabled) |
| Detection end | {prefix}/detection/end | camera, duration_ms, stages_executed |
| Pipeline error | {prefix}/detection/error | camera, stage, error message |
| Service online | {prefix}/status (LWT) | payload: online, retain: true |
| Service offline | {prefix}/status (LWT) | payload: offline, retain: true (set at connect) |

- MQTT credentials hot-reload: when mqtt config changes, publisher disconnects and reconnects without service restart
- LWT (Last Will and Testament) registered at connect time for reliable offline detection

---

## Section 6: TTS Providers

piper -> kokoro -> elevenlabs -> cartesia -> polly -> openai -> espeak
(espeak always appended as final fallback)

---

## Section 7: AI Providers

gemini (video+images, auto-selects model in UI) -> openai (images) -> anthropic (images) -> grok (images) -> ollama (single image) -> custom (images)

---

## Section 8: New Files

| File | Purpose |
|------|---------|
| voxwatch/mqtt_publisher.py | MQTT event publisher module. Handles connect/disconnect, LWT registration, event serialization, hot-reload on credential change, and topic-prefixed publish for all pipeline events. |
| docs/HOME_ASSISTANT.md | Home Assistant automation examples: trigger automations from VoxWatch MQTT events, sample YAML for detection start/end, stage events, and online/offline status tracking. |

---

## Section 9: UI Component Changes

### Persona Customization Panels (new)

| Panel | Config field written | Location |
|-------|---------------------|----------|
| Guard Dog Names | response_mode.guard_dog.dog_names | Personality tab |
| Surveillance Preset | response_mode.surveillance_preset | Personality tab |
| Live Operator Name | response_mode.operator_name | Personality tab |
| Homeowner Mood | response_mode.mood | Personality tab |

### Test Buttons (new -- Connections tab)

| Button | Calls | Requires auth |
|--------|-------|---------------|
| Test Frigate | POST /api/setup/test-frigate | Yes (dashboard API key) |
| Test MQTT | POST /api/setup/test-mqtt | Yes |
| Test go2rtc | POST /api/setup/test-go2rtc | Yes |

### MQTT Publishing Config Section (new -- Connections tab)

Four fields exposed in UI: enabled, topic_prefix, include_ai_analysis, include_snapshot_url (maps to mqtt_publish.* config fields).

### Email Camera Report Popup (CameraReportPrompt.tsx)

| Field | Detail |
|-------|--------|
| Trigger | User clicks "Email Report" action on a camera |
| Display | Modal dialog with To, Subject, and Body fields |
| Copy buttons | Each field (To, Subject, Body) has a dedicated Copy button |
| Previous behavior | Used mailto: links (replaced with modal + copy workflow) |

### Other UI Changes

| Change | Detail |
|--------|--------|
| Supporter badges removed | Replaced with Customizable feature chips |
| Camera auto-identify | Clicking a camera in the wizard automatically triggers POST /api/cameras/{name}/identify |
| Gemini model auto-selection | AI Provider tab auto-populates recommended Gemini model when Gemini provider is selected |
| Pipeline defaults cleared | prefix and suffix fields default to empty string instead of placeholder text |
| Response Mode -> Personality | Label rename in Pipeline tab section header |

---

## Section 10: Known Issues

1. Backchannel warmup required (first push discarded)
2. Reolink=PCMU, Dahua=PCMA codec mismatch
3. ONVIF identify fails on some cameras
4. go2rtc stream name must match exactly
5. Rate limits reset on process restart
6. Masked secrets restored from disk on PUT
7. ${ENV_VAR} tokens unresolved in dashboard
8. Events log rotates at 5MB
9. Wizard temp files cleaned on next test-audio call
10. SPA catch-all has path traversal guard
11. Dispatch preview requires VoxWatch on port 8892
12. Config validators run in order (cameras -> enabled)
13. Natural cadence falls back to flat-string TTS if any ffmpeg step fails
14. mqtt_publish.* fields require service restart for LWT re-registration (hot-reload updates credentials only)

---

## Section 11: Natural Cadence System

### Module: voxwatch/speech/natural_cadence.py

| Item | Detail |
| ------ | -------- |
| Entry point | generate_natural_speech(phrases, audio_pipeline, output_path, config, cadence_config=None) -> bool |
| Config dataclass | CadenceConfig -- 11 fields, built via CadenceConfig.from_config(config) |
| AI response parser | parse_ai_response(response: str) -> list[str] |
| Pause calculator | determine_pause_duration(phrase, cadence_config) -> float |
| Silence generator | generate_silence(duration, sample_rate, output_path) -> bool (async, ffmpeg lavfi anullsrc) |
| Speed variation | apply_speed_variation(input_path, output_path, speed) -> bool (async, ffmpeg atempo) |
| Segment concat | concatenate_segments(segment_paths, output_path) -> bool (async, ffmpeg concat demuxer) |
| Format normalise | _convert_to_work_format(input_path, output_path) -> bool (internal, 44.1 kHz 16-bit mono) |
| Working format | PCM 16-bit signed, 44100 Hz, mono -- all intermediate files |
| ffmpeg timeout | 30 seconds per subprocess call |
| Fallback | Returns False; caller falls back to audio_pipeline.generate_tts flat string |
| Temp cleanup | TemporaryDirectory always cleaned in finally block |

### parse_ai_response() -- Input Format Priority

| Priority | Format | Detection |
| ---------- | -------- | ----------- |
| 1 | JSON array inside markdown code block | regex inside code fences, re.DOTALL |
| 2 | Bare JSON array anywhere in string | regex match, re.DOTALL |
| 3 | Plain text sentence split | re.split on sentence-ending punctuation |
| Fallback | Entire response as single phrase | When all strategies yield empty |

### CadenceConfig -- 11 Parameters (config section: speech.natural_cadence)

| Parameter | Type | Default | Config key |
| --------- | ---- | ------- | ---------- |
| min_pause | float | 0.2s | speech.natural_cadence.min_pause |
| max_pause | float | 0.6s | speech.natural_cadence.max_pause |
| period_pause | float | 0.5s | speech.natural_cadence.period_pause |
| ellipsis_pause | float | 0.7s | speech.natural_cadence.ellipsis_pause |
| comma_pause | float | 0.2s | speech.natural_cadence.comma_pause |
| min_speed | float | 0.92 | speech.natural_cadence.min_speed |
| max_speed | float | 1.08 | speech.natural_cadence.max_speed |
| speed_variation_enabled | bool | True | speech.natural_cadence.speed_variation |
| leading_pause | float | 0.3s | speech.natural_cadence.leading_pause |
| trailing_pause | float | 0.2s | speech.natural_cadence.trailing_pause |
| postprocess | bool | True | speech.natural_cadence.postprocess |

### Pause Duration Rules (determine_pause_duration)

| Trailing punctuation | Pause used |
| --------------------- | ---------- |
| ... (ellipsis) | ellipsis_pause (0.7s default) |
| . ! ? | period_pause (0.5s default) |
| , ; : | comma_pause (0.2s default) |
| None / other | random uniform in [min_pause, max_pause] |

### Module: voxwatch/speech/postprocess.py

| Item | Detail |
| ------ | -------- |
| Entry point | apply_natural_postprocess(input_path, output_path) -> bool (async) |
| Filter chain | silenceremove -> acompressor (3:1 ratio, -18 dB threshold) -> loudnorm (-16 LUFS) |
| Silence threshold | -50 dB, 0.1s minimum duration (prevents trimming inter-phrase gaps) |
| Target loudness | -16 LUFS integrated (EBU R128 / ITU-R BS.1770), TP=-1.5, LRA=11 |
| Output format | PCM 16-bit, 44100 Hz, mono |
| Invocation | Called lazily from generate_natural_speech when CadenceConfig.postprocess=True |
| Failure mode | Non-fatal -- generate_natural_speech logs warning and uses unprocessed audio |

### AudioPipeline Integration

| Method | Description |
| ------- | ----------- |
| AudioPipeline.generate_natural_tts(phrases, output_path) | Calls generate_natural_speech; on False return falls back to standard generate_tts |

### Config Section: speech.natural_cadence

Sits under the top-level speech key in config.yaml. All 11 parameters from CadenceConfig are read here. Missing keys use dataclass defaults -- the section is entirely optional.

### Test Coverage: tests/test_natural_cadence.py

| Test step | What is verified |
| --------- | ---------------- |
| 1 -- parse_ai_response | JSON array, JSON code block, plain text sentence split -- all return correct phrase list |
| 2 -- determine_pause_duration | period_pause, ellipsis_pause, comma_pause, no-punct in [min, max] |
| 3 -- generate_silence | 0.5s lavfi silence WAV exists and >= 200 bytes |
| 4 -- apply_speed_variation | atempo 1.05x output exists and >= 200 bytes |
| 5 -- apply_natural_postprocess | compression + loudnorm output exists and >= 200 bytes |
| 6 -- Full A/B pipeline | cadence WAV vs flat espeak WAV both generated for listening comparison |

---

## Section 12: Response Modes System

### Modules

| Module | Exports |
| ------- | -------- |
| voxwatch/modes/mode.py | ResponseMode, ToneConfig, VoiceConfig, BehaviorConfig, StageConfig |
| voxwatch/modes/loader.py | load_modes, get_active_mode, get_mode_prompt, get_mode_template, build_ai_vars, extract_ai_vars_from_dispatch_json |
| voxwatch/modes/__init__.py | Re-exports all of the above as the public API |

### ResponseMode Dataclass Hierarchy



### Built-in Modes (9 total)

| ID | Category | Name |
| ---- | --------- | ------ |
| police_dispatch | core | Police Dispatch |
| live_operator | core | Live Operator |
| private_security | core | Private Security |
| homeowner | core | Homeowner |
| evidence_collection | core | Evidence Collection |
| standard | core | Standard (fallback) |
| silent_pressure | advanced | Silent Pressure |
| neighborhood_alert | advanced | Neighborhood Alert |
| automated_surveillance | advanced | Automated Surveillance |

### loader.py Public API

| Function | Signature | Description |
| ---------- | ----------- | ------------- |
| load_modes | (config) -> dict[str, ResponseMode] | Loads built-ins, merges user-defined modes from response_modes.modes |
| get_active_mode | (config, camera_name=None) -> ResponseMode | Resolves active mode; honours per-camera overrides; falls back to standard |
| get_mode_prompt | (mode_def, stage, ai_vars) -> str | Returns AI system prompt with mode prompt_modifier applied and vars substituted |
| get_mode_template | (mode_def, stage, ai_vars, index=0) -> str | Renders fallback template string with variable substitution |
| build_ai_vars | (config, camera_name, ...) -> dict | Assembles all 8 AI description variables with neutral fallbacks |
| extract_ai_vars_from_dispatch_json | (ai_json_str) -> dict | Parses dispatch-mode JSON AI response into AI vars dict |

### Mode Resolution Order (get_active_mode)

1. response_modes.camera_overrides[camera_name] -- per-camera override (highest priority)
2. response_modes.active_mode -- global active mode
3. response_mode.name or persona.name -- legacy single-key format
4. standard -- final fallback if mode ID not found in loaded library

### AI Description Variables (8 total)

| Variable | Source | Neutral fallback |
| --------- | -------- | ---------------- |
| {clothing_description} | AI vision response | the individual |
| {location_on_property} | AI vision response | the property |
| {behavior_description} | AI vision response | their current actions |
| {suspect_count} | AI vision response | one |
| {address_street} | config.property.street | this address |
| {address_full} | config.property.full_address | this address |
| {time_of_day} | datetime.now().hour at call time | this hour |
| {camera_name} | Frigate detection event | the camera |

Time-of-day labels: early morning (hours 5-8), morning (9-11), afternoon (12-16), evening (17-20), night (all other hours).

### Per-Camera Mode Overrides (config.yaml)



Override lookup uses exact camera name string match against camera_overrides dict keys.

### Custom Mode Support

User-defined modes in config.yaml under response_modes.modes are parsed via _parse_mode_from_dict.
Required field: id. Optional: category (default custom), name, description, effect, tone.*, voice.*, behavior.*, stage templates.
Invalid entries are logged and skipped without crashing the service.

### Variable Substitution Safety

_substitute_vars uses _SafeFormatMap (dict subclass). Unknown placeholder tokens returned as-is. Malformed format strings returned unchanged.

### extract_ai_vars_from_dispatch_json

Parses a JSON object string from dispatch-mode AI responses. Field mapping:
- description -> clothing_description
- location -> location_on_property
- suspect_count -> suspect_count
- behavior or movement -> behavior_description

On JSON parse failure: returns dict with all empty-string values (non-fatal).

---

*Generated: 2026-03-27 | Version: 1.5 | Update on any API, component, or config change*

---

## Section 13: Error Surfacing and TTS Fallback Pipeline (added 2026-03-27)

### voxwatch/tts/base.py -- TTSResult.fallback_reason

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| fallback_reason | str | "" | Human-readable reason why primary TTS failed and a fallback provider was used. Empty string when no fallback occurred. Set by factory.generate_with_fallback() on the returned result. |

### voxwatch/tts/factory.py -- _build_provider return type

_build_provider(name, config) returns tuple[TTSProvider | None, str]:
- On success: (provider_instance, "")
- On failure: (None, error_description_string)

All callers unpack with: provider, _err = _build_provider(...)
This allows the factory to report why a provider was skipped without propagating exceptions.
The error string is captured as primary_failure_reason and attached to TTSResult.fallback_reason when a fallback provider succeeds.

### voxwatch/ai_vision.py -- _last_ai_error / get_last_ai_error()

| Item | Detail |
|------|--------|
| Module-level var | _last_ai_error: str = "" -- tracks the last AI analysis failure across calls |
| Accessor | get_last_ai_error() -> str -- returns the stored error string or "" if last call succeeded |
| Reset | Set to "" on every successful analyze_snapshots() return |
| Set on failure | Both-providers-failed path: combines primary and fallback error strings |
| Purpose | Read by the service layer to publish MQTT error events without re-raising exceptions |

### voxwatch/audio_pipeline.py -- AudioPipeline error publisher

| Method | Signature | Description |
|--------|-----------|-------------|
| set_error_publisher | (publisher: Any) -> None | Attaches an MQTT publisher object; called by VoxWatchService after pipeline construction |
| _publish_pipeline_error | (error_type: str, error_message: str, camera: str = "", stage: int = 0) -> None | Calls publisher.publish_error(...) if publisher is attached; catches all exceptions |

Error types published: tts_failed, audio_conversion_failed, audio_push_failed, go2rtc_sender_leak

Call sites: generate_tts() on all-providers-exhausted; convert_to_camera_codec() on ffmpeg failure/timeout/not-found; push_audio_to_camera() on go2rtc HTTP error/timeout/generic exception; _check_sender_count() on leak threshold exceeded.

### dashboard/backend/models/status_models.py -- VoxWatchServiceStatus

New model added to SystemStatus. Read from /data/status.json by _read_voxwatch_status() in status.py. Staleness threshold: 30 seconds (mtime > 30s -> reachable=False).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| reachable | bool | False | True if status.json was readable and mtime < 30 seconds ago |
| service_running | bool | False | From status.json key service_running |
| mqtt_connected | bool | False | From status.json key mqtt_connected |
| uptime_seconds | float | None | From status.json key uptime_seconds |
| version | str | None | From status.json key version |
| error | str | None | Human-readable error if file is missing, stale, or unreadable |

GET /api/status response now includes a voxwatch: VoxWatchServiceStatus field (previously omitted from the baseline). SystemStatus.voxwatch has default_factory=VoxWatchServiceStatus so the field is always present.

### voxwatch/telemetry.py -- status.json shape (written by VoxWatch service)

Keys in status.json consumed by _read_voxwatch_status():

| JSON key | Consumed by VoxWatchServiceStatus field |
|----------|-----------------------------------------|
| service_running | service_running |
| mqtt_connected | mqtt_connected |
| uptime_seconds | uptime_seconds |
| version | version |

Additional keys in the file (not surfaced in VoxWatchServiceStatus): started_at, active_hours_active, cameras (per-camera stats dict with enabled, last_detection_at, cooldown_until, total_detections, total_audio_pushes, last_audio_push_success).

### Response Headers -- POST /api/audio/preview

New response headers forwarded by the preview endpoint:

| Header | Value | Meaning |
|--------|-------|---------|
| X-TTS-Fallback | "true" or "false" | Set by VoxWatch Preview API and forwarded by dashboard. "true" when any fallback provider was used |
| X-TTS-Fallback-Reason | error string | Why primary TTS failed; only present when fallback was used |
| X-TTS-Provider | provider name | Which TTS provider actually generated audio |
| X-TTS-Configured | provider name | Which TTS provider was requested/configured |
| X-VoxWatch-Proxy | "proxied" or "local-fallback" | Set only by dashboard audio.py. "proxied" = forwarded to VoxWatch Preview API; "local-fallback" = VoxWatch unreachable, dashboard synthesized locally |
| X-Generation-Time-Ms | integer string | Audio synthesis time in milliseconds |

Forwarding chain: voxwatch/preview_api.py sets X-TTS-Fallback-Reason -> dashboard audio.py forwards it -> browser reads it.

### dashboard/frontend/src/api/status.ts -- AudioPreviewResult extended fields

| Field | Type | Source header | Description |
|-------|------|---------------|-------------|
| fallbackReason | string (optional) | X-TTS-Fallback-Reason | Reason primary TTS failed; undefined when no fallback |
| proxyFallback | boolean (optional) | X-VoxWatch-Proxy === "local-fallback" | True when VoxWatch unreachable and dashboard fell back to local synthesis |

### dashboard/frontend/src/components/common/AudioPreview.tsx -- new props

| Prop | Type | Behavior |
|------|------|----------|
| fallbackReason | string (optional) | Renders a sub-line below the TTS fallback warning with the formatted failure reason |
| proxyFallback | boolean (optional) | When true, renders an amber alert banner explaining preview lacks full VoxWatch pipeline effects |

### dashboard/frontend/src/components/audio/TestAudioButton.tsx -- amber unverified state

After a successful POST /api/audio/test response the camera button enters an amber state (border-amber-500, AlertTriangle icon). This signals the API call succeeded but acoustic verification at the camera has not been confirmed. State is local to the component and resets on page refresh.

### dashboard/backend/routers/audio.py -- cloud TTS nested config resolution

_resolve_cloud_tts_key(key_name) two-tier lookup:
1. Nested: tts.<provider>.api_key (e.g. tts.openai.api_key)
2. Flat fallback: tts.<key_name> (e.g. tts.openai_api_key)

${ENV_VAR} tokens resolved to live env var values. Masked values (starting with "***") treated as missing. Used by ElevenLabs, OpenAI, Cartesia, and Polly preview handlers.

---

## Section 14: Novelty Persona Removal (2026-03-27)

Novelty category built-in personas were removed: tony_montana_dispatch, mafioso, pirate_captain, british_butler, disappointed_parent.

### Current state after removal

- Built-in modes count: 9 (unchanged -- see Section 12 table)
- FUN_MODES array in ResponseModeStep.tsx: empty (FUN_MODES = [])
- _DISPATCH_MODES in audio.py: frozenset({"police_dispatch"}) only

### Stale references remaining (known, non-functional, no action required)

| File | Reference | Type |
|------|-----------|------|
| dashboard/backend/routers/audio.py:972 | Comment mentions tony_montana_dispatch | Comment artifact |
| voxwatch/config.py:210 | Comment mentions Tony Montana and novelty modes | Comment artifact |
| voxwatch/modes/mode.py:26 | Docstring lists "novelty" category | Category still valid for user-defined modes |
| voxwatch/modes/loader.py:321 | Same novelty category docstring | Category still valid for user-defined modes |
| dashboard/frontend/src/types/config.ts:560,563 | ResponseMode.category includes "novelty" union member | Still valid for user-defined custom modes |
| dashboard/backend/models/config_models.py:702 | Comment references "mafioso" as example key | Comment artifact |
| dashboard/frontend/src/components/setup/steps/ResponseModeStep.tsx:173 | JSDoc references "fun/novelty groups" | The toggle renders but FUN_MODES=[] so no cards appear |
| voxwatch/voxwatch_service.py:2003 | Comment example references "mafioso" | Comment artifact |

None cause runtime errors, lint failures, or TypeScript errors. The "Fun / Novelty" toggle in the wizard renders but is visually empty.



---

## Section 15: Piper Voice Auto-Download System (added 2026-03-27)

### voxwatch/tts/providers/piper_provider.py -- model resolution

PiperProvider._resolve_model(model_name) resolves a config value to the best
available path using a fixed priority chain:

| Priority | Condition | Action |
|----------|-----------|--------|
| 1 | os.path.exists(model_name) | Use as-is (absolute path) |
| 2 | /usr/share/piper-voices/<model>.onnx exists | Use baked-in Docker image voice |
| 3 | /data/piper-voices/<model>.onnx exists | Use previously auto-downloaded cache |
| 4 | Neither found | Attempt auto-download from Hugging Face |
| 5 | Download fails | Try PIPER_MODEL_PATH env var (legacy Dockerfile default) |
| 6 | Env var missing/invalid | Pass raw name to piper binary for its own resolution |

### Auto-download constants

| Constant | Value | Description |
|----------|-------|-------------|
| _DOWNLOAD_DIR | /data/piper-voices | Persistent download cache directory |
| _HF_BASE | https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0 | Standard Hugging Face base URL |
| _SUBPROCESS_TIMEOUT | 30 seconds | Max time to wait for piper binary |

### _CUSTOM_VOICES registry

Maps non-standard model names to explicit (onnx_url, json_url) tuples. Checked
before the standard rhasspy URL pattern in _hf_url(). Current entries:

| Key | Repo | Description |
|-----|------|-------------|
| hal9000 | campwill/HAL-9000-Piper-TTS | Calm monotone AI voice |

### _hf_url(model_name) behavior

Checks _CUSTOM_VOICES first. For standard names, splits on "-" expecting at least 3
parts: <lang_region>-<voice>-<quality>. Raises ValueError if parsing fails (prevents
download attempt with garbage model name).

### _download_model(model_name) behavior

Downloads .onnx.json config first (small), then .onnx model (20-60 MB).
On any exception: logs warning, removes partial files (both paths), returns None.
On success: returns path to the downloaded .onnx file.

---

## Section 16: Piper Voice Management API (added 2026-03-27)

### GET /api/audio/piper-voices

Lists all known Piper voice models with installation status.

- No request body required.
- Response model: PiperVoiceListResponse { voices: list[PiperVoiceInfo], builtin_dir: str, downloaded_dir: str }
- Scans /usr/share/piper-voices/ (builtin) and /data/piper-voices/ (downloaded).
- Merges scan results with _PIPER_VOICE_INFO friendly-name registry (11 known voices).
- Unknown .onnx files found on disk are included with id as label.
- Missing directories return empty results without error.

### PiperVoiceInfo fields

| Field | Type | Description |
|-------|------|-------------|
| id | str | Model identifier (e.g. en_US-lessac-medium) |
| label | str | Human-readable name (e.g. Lessac (Medium)) |
| desc | str | Short description of voice character and quality |
| installed | bool | True if .onnx file is present on disk |
| size_mb | float or null | File size in MB; null when not installed |
| source | str | builtin, downloaded, or available |

### DELETE /api/audio/piper-voices/{model_name}

Deletes a downloaded Piper voice model. Dashboard container mounts /data
read-only, so the request is proxied to VoxWatch Preview API.

| HTTP code | Condition |
|-----------|-----------|
| 200 | Deletion successful |
| 400 | model_name contains characters outside ^[a-zA-Z0-9_-]+$ |
| 403 | Model is builtin (in /usr/share/piper-voices/) |
| 404 | Model not found in /data/piper-voices/ |
| 503 | VoxWatch Preview API unreachable |

Proxy target: VoxWatch Preview API DELETE /api/piper-voices/{model_name}.
Both .onnx and .onnx.json files are deleted. Partial-delete is not possible
(both files removed in one handler call).

### VoxWatch Preview API -- DELETE /api/piper-voices/{model_name}

Registered in preview_api.py at startup via app.router.add_delete().

Validation:
- model_name must match ^[a-zA-Z0-9_-]+$ (HTTP 400 otherwise)
- Builtin check: if /usr/share/piper-voices/<model>.onnx exists -> HTTP 403
- Not-found check: if /data/piper-voices/<model>.onnx not found -> HTTP 404
- Deletes both <model>.onnx and <model>.onnx.json (suppresses OSError on json removal)

---

## Section 17: Preview Voice Override Mapping (added 2026-03-27)

### voxwatch/preview_api.py -- _build_preview_config()

When a generic voice override is supplied in the preview request body,
_build_preview_config() maps it to the provider-specific config key that the
TTS factory actually reads. This ensures the correct voice is used regardless
of which provider is active.

| Active provider | Config key written |
|-----------------|--------------------|
| piper | tts.piper_model |
| kokoro | tts.kokoro_voice |
| elevenlabs | tts.elevenlabs_voice_id |
| openai | tts.openai_voice |
| cartesia | tts.cartesia_voice_id |

Provider resolved from new_tts.get("provider", "piper") after override merge.
Mapping only applied when a voice key is present in the incoming override dict.

---

## Section 18: Kokoro Test Button (added 2026-03-27)

### POST /api/audio/test-tts-provider -- kokoro provider

Provider field value: kokoro. Host URL passed in the api_key request field
(repurposed since Kokoro has no API key). Falls back to reading from config
(tts.kokoro.host then tts.kokoro_host then http://localhost:8880).

Probe sequence:
1. GET {host}/voices (Kokoro native endpoint)
2. If HTTP 404: GET {host}/v1/audio/voices (OpenAI-compatible wrapper)
3. If both 404: return ok=False

On success: returns ok=True with voice count.
/voices returns {"voices": {"lang": [...]}}, flattened list count.
/v1/audio/voices returns flat list, counted directly.

### Frontend -- TtsConfigForm.tsx KokoroFields section

TestApiAccessButton rendered for Kokoro with provider="kokoro" and
apiKey=value.kokoro_host. Consistent with ElevenLabs, Cartesia, OpenAI,
and Polly test buttons in the same form.

---

## Section 19: Fallback Reason Header Sanitization (added 2026-03-27)

### voxwatch/preview_api.py -- X-TTS-Fallback-Reason sanitization

Applied immediately before setting the response header. Three transforms:
1. Replace all newline characters with a space.
2. Remove all carriage return characters.
3. Truncate to 500 characters maximum.

Rationale: aiohttp rejects headers containing raw newlines or carriage returns,
which would cause the response to fail rather than simply omit the reason.

Code location: immediately after the if fallback_reason: check in _handle_preview.

---

## Section 20: Engine vs Provider Config Priority Fix (added 2026-03-27)

### voxwatch/config.py -- _apply_defaults() engine/provider resolution

Config fields: tts.engine (written by dashboard UI) vs tts.provider (read by TTS factory).

Previous behavior: engine only copied to provider when provider was absent.
Bug: if both keys existed, stale provider value won.

Current behavior: engine ALWAYS overwrites provider when present.
engine is the most-recent source of truth (set by dashboard on every save).

    if "engine" in tts_cfg:
        tts_cfg["provider"] = tts_cfg["engine"]
    tts_cfg.setdefault("provider", "piper")

Failure mode fixed: user switches kokoro -> piper in UI. Dashboard writes
engine=piper but provider=kokoro from prior save persists. Without fix,
factory starts Kokoro instead of Piper.

---

## Section 21: Stale Novelty Persona Reference Cleanup (added 2026-03-27)

README.md and all docs/ files confirmed clean: no matches for tony_montana,
mafioso, pirate_captain, british_butler, disappointed_parent, or novelty.

Remaining artifacts in Python/TypeScript source files are documented in
Section 14. They are comment/docstring artifacts with no runtime effect.
No new stale references were introduced in this session.

---

## Section 22: Frontend PiperFields UI (added 2026-03-27)

### dashboard/frontend/src/components/config/TtsConfigForm.tsx -- PiperFields

Rendered when tts.engine === piper in the TTS config form.

#### Voice dropdown

- Populated from PIPER_VOICES static list (11 known voices including hal9000).
- Install status fetched via GET /api/audio/piper-voices (React Query, staleTime: 30s).
- Option suffix: checkmark (U+2713) when installed; (downloads on first use) when not.
  No suffix shown until API data loads.
- On change: writes to tts.piper_model.

#### Auto-download info banner

Blue info box below the dropdown. Text: Only the default voice (Lessac Medium)
is pre-installed. Other voices download automatically on first preview (~20-60 MB each).

#### Installed Voices section

Bordered panel showing all voices where installed=true from the API response.

| Column | Content |
|--------|---------|
| Label | Voice label in a code element |
| Size | size_mb to 1 decimal place; only shown when not null |
| Badge/action | green pre-installed badge for builtin; trash delete button for downloaded |

Delete button:
- Calls DELETE /api/audio/piper-voices/{id} via deletePiperVoice() API function.
- Disabled while deleteMutation.isPending (prevents double-tap race).
- On success: invalidates piper-voices React Query key to refresh install status.

Empty state: No additional voices downloaded when installedVoices list is empty.

---

*Generated: 2026-03-27 | Version: 1.5 | Update on any API, component, or config change*

---

## Section 23: QA Audit Log (2026-03-27 v1.5 full audit)

This section records all findings from the comprehensive v1.5 baseline audit
conducted against the full codebase. Classifications: ADDED (new coverage not
previously documented), CORRECTED (inaccuracy fixed), CONFIRMED (verified
accurate against source, no change required).

### Build Verification Results

| Check | Result |
|-------|--------|
| python -m ruff check voxwatch/ | PASS -- All checks passed, zero lint errors |
| cd dashboard/frontend && npx tsc --noEmit | PASS -- Zero TypeScript type errors |

---

### Section 1 Audit Findings

**Three endpoints existed in code but were absent from the Section 1 endpoint list.**
All three have now been inserted above GET /api/cameras.

| Endpoint | Status | File | Line |
|----------|--------|------|------|
| GET /api/status/events | ADDED | dashboard/backend/routers/status.py | 311 |
| GET /api/audio/piper-voices | ADDED | dashboard/backend/routers/audio.py | 1990 |
| DELETE /api/audio/piper-voices/{model_name} | ADDED | dashboard/backend/routers/audio.py | 2096 |
| POST /api/audio/test-tts-provider | ADDED | dashboard/backend/routers/audio.py | 1613 |

Note: POST /api/system/test-tts (system.py line 382) is a different endpoint
from POST /api/audio/test-tts-provider (audio.py line 1613). The former was
already documented; the latter was missing from Section 1.

GET /api/status description updated to note that the response now includes a
`voxwatch: VoxWatchServiceStatus` field (populated from /data/status.json).

---

### Section 13 Audit Findings

**Response headers table was incomplete.**

The original table listed only X-TTS-Fallback-Reason and X-VoxWatch-Proxy.
Four additional headers are sent on every successful preview response and are
now documented.

Corrected table covers all six headers:

| Header | Set by | Value |
|--------|--------|-------|
| X-TTS-Fallback | preview_api.py (forwarded by dashboard) | "true" or "false" |
| X-TTS-Fallback-Reason | preview_api.py (forwarded by dashboard) | error string or absent |
| X-TTS-Provider | preview_api.py (forwarded by dashboard) | provider name that ran |
| X-TTS-Configured | preview_api.py (forwarded by dashboard) | provider name requested |
| X-VoxWatch-Proxy | dashboard audio.py only | "proxied" or "local-fallback" |
| X-Generation-Time-Ms | preview_api.py (forwarded by dashboard) | integer ms string |

Key distinction: X-TTS-Fallback is set by preview_api.py and forwarded.
X-VoxWatch-Proxy is only added by dashboard audio.py -- preview_api.py never
sets it. This header marks whether the dashboard proxied or synthesized locally.

---

### Section 16 Audit Findings

**PiperVoiceListResponse model was documented incompletely.**

Original: PiperVoiceListResponse { voices: list[PiperVoiceInfo] }
Actual (audio.py line 1976): also includes builtin_dir: str and downloaded_dir: str

Both are required fields (no default). builtin_dir is always "/usr/share/piper-voices"
and downloaded_dir is always "/data/piper-voices" in normal deployments.

This correction has been applied in both Section 1 and Section 16.

_PIPER_VOICE_INFO count confirmed as 11 entries (verified at audio.py line 1877).

---

### All Other Sections: Confirmed Accurate

The following items were verified against source code and found accurate.
No changes were required.

**Section 14 (Novelty Persona Removal)**
- audio.py _DISPATCH_MODES = frozenset({"police_dispatch"}) confirmed at line 1010.
  This is a local copy independent of radio_dispatch.py DISPATCH_MODES.
- radio_dispatch.py DISPATCH_MODES confirmed at line 72. DISPATCH_PERSONAS is alias.

**Section 15 (Piper Auto-Download)**
- 6-step _resolve_model priority chain confirmed in piper_provider.py lines 129-180.
- _CUSTOM_VOICES with hal9000 confirmed at piper_provider.py line 44.
- _DOWNLOAD_DIR=/data/piper-voices, _HF_BASE URL, _SUBPROCESS_TIMEOUT=30 all confirmed.

**Section 17 (Preview Voice Override Mapping)**
- _build_preview_config voice-to-provider mapping confirmed at preview_api.py lines 968-983.
- Five mappings: piper->piper_model, kokoro->kokoro_voice, elevenlabs->elevenlabs_voice_id,
  openai->openai_voice, cartesia->cartesia_voice_id.

**Section 18 (Kokoro Test Button)**
- Two-endpoint probe sequence confirmed at audio.py lines 1786-1823.
- Host resolution order confirmed: request.api_key -> tts.kokoro.host ->
  tts.kokoro_host -> http://localhost:8880.

**Section 19 (Fallback Reason Header Sanitization)**
- Three transforms confirmed at preview_api.py lines 332-333:
  replace("\n", " "), replace("\r", ""), [:500].

**Section 20 (Engine vs Provider Priority Fix)**
- _apply_defaults unconditional assignment confirmed at voxwatch/config.py lines 119-121.

**VoxWatch Service Behaviors**
- _play_initial_response: returns tuple[bool, str | None] (voxwatch_service.py:1074).
- _run_escalation: returns tuple[str | None, bool, str | None] (line 1146).
- Enriched event log fields (tts_message, escalation_message, tts_provider,
  tts_voice, ai_provider) confirmed at lines 1038-1046.
- get_last_ai_error() + _last_ai_error module var confirmed at ai_vision.py lines 97-117.

**Audio Pipeline Behaviors**
- set_error_publisher / _publish_pipeline_error confirmed at audio_pipeline.py lines 257/261.
- Error types: tts_failed, audio_conversion_failed, audio_push_failed, go2rtc_sender_leak.
- _last_fallback_reason, _tts_provider_status, _tts_provider_error, _sender_counts
  confirmed as instance attributes at lines 143-164.
- generate_and_push persona null guard: double-null pattern at lines 1208-1209.
  cfg = self.config or {} then (cfg.get("persona") or {}).get("name", "standard").

**Radio Dispatch Behaviors**
- _generate_chatter_tts uses dispatcher voice confirmed at radio_dispatch.py line 1687.
  Builds provider-specific config copy before calling audio_pipeline.generate_tts().

**Security**
- dashboard/entrypoint.sh drops to "dashboard" user (su-exec pattern).
- entrypoint.sh drops to "voxwatch" user.
- Preview API binds to 127.0.0.1 confirmed at preview_api.py line 130.
- espeak -- sentinel confirmed at espeak_provider.py generate() method.
- TTS input sanitization _sanitize_tts_input() confirmed at audio_pipeline.py line 69.
- Piper model name _validate_model_name() confirmed at audio.py line 1898.

**Frontend Components**
- RecentActivity.tsx: clickable accordion, renders tts_message/escalation_message/
  tts_provider/ai_provider. Polls /api/status/events every 15s.
- PiperFields: React Query staleTime 30s, checkmark when installed, delete
  mutation invalidates piper-voices cache, disabled while isPending.
- PersonaConfigForm: dispatch persona has dispatcher_voice (kokoro),
  dispatcher_openai_voice, dispatcher_elevenlabs_voice. Non-dispatch personas
  have no voice override fields.
- AudioPreview: fallbackReason prop (line 86), proxyFallback prop (line 93),
  playbackError useState (line 131). All render correctly.
- TestAudioButton: amber state (border-amber-500 + AlertTriangle) on isSuccess.
- ConfigSaveBar: change-review panel at bottom-28 mobile / bottom-14 md+.
  AppShell content area uses pb-24 mobile / md:pb-20.

---

*Generated: 2026-03-27 | Version: 1.5 | Full audit against codebase*

---

## Section 24: False Positive Detection -- AI All-Unknown Skip (added 2026-03-28)

### voxwatch/voxwatch_service.py -- escalation guard

When the dispatch escalation stage receives an AI response (JSON object), the
service checks whether both description and location fields are "unknown"
or empty. If both are indeterminate, the event is classified as a likely
Frigate false positive and the escalation is suppressed.

| Condition checked | Values that trigger skip |
|-------------------|-------------------------|
| description field | "unknown" or "" (case-insensitive, stripped) |
| location field | "unknown" or "" (case-insensitive, stripped) |
| Both must match | Single-field unknown does NOT suppress escalation |

| Behavior when skip is triggered | Detail |
|---------------------------------|--------|
| Stage 1 (initial warning) | Already played -- not suppressed |
| Stage 2 (escalation) | Skipped; _escalation_ran = False |
| Log message | Escalation: AI returned all-unknown description -- likely false positive from Frigate. Skipping escalation. |
| MQTT error event published | error_type="false_positive" |
| JSON parse failure | Exception caught silently; escalation proceeds as normal |

Call site: voxwatch_service.py inside _handle_detection(), after AI
analysis result is available and before _run_escalation() is called.

---

## Section 25: Dispatch Pipeline Fixes (added 2026-03-28)

### 25a: Stage 1 is a Direct Warning for Dispatch Modes (not radio)

For police_dispatch (and all modes in DISPATCH_MODES), the Stage 1 initial
response is a short direct deterrent warning rendered via the global TTS voice
(not the dispatcher voice). The full radio treatment (10-codes, officer
response, radio effects, priority alert) is reserved for the Escalation stage.

| Item | Detail |
|------|--------|
| Code location | voxwatch_service._play_initial_response(), line ~1164 |
| Logic | stage1_voice = None if mode_name in DISPATCH_MODES else voice_config |
| Effect | None voice config causes generate_and_push to use global TTS settings |
| Dispatcher voice | Only activated during _play_dispatch_escalation() |
| Stage 1 text | Comes from the mode stage1 template (same as non-dispatch modes) |

### 25b: Dispatch Escalation Uses stage_label="stage2" (not "stage3")

The dispatch escalation call (_play_dispatch_escalation) passes
stage_label="stage2" to _play_dispatch_stage. This is correct because the
AI always returns the Stage 2 appearance schema (suspect_count / description /
location). Using "stage3" (behavioral schema) was the previous bug.

| Item | Detail |
|------|--------|
| Fixed call site | voxwatch_service._play_dispatch_escalation(), line ~1485 |
| stage_label passed | "stage2" |
| Stage 2 schema fields | suspect_count, description, location |
| Stage 3 schema fields | behavior, movement (not used by dispatch escalation) |
| Impact of bug | Wrong tone config key (stage3_tone) was used for attention beep lookup |

### 25c: Priority Alert Tone in Dispatch Audio

A three-tone ascending priority alert is generated and prepended before the
first dispatch segment in every dispatch audio sequence.

| Constant | Value | Description |
|----------|-------|-------------|
| _ALERT_TONE_FREQS | [1000, 1200, 1400] Hz | Ascending beep frequencies |
| _ALERT_TONE_BEEP_DURATION | 0.15 s | Duration of each beep |
| _ALERT_TONE_GAP_DURATION | 0.08 s | Silence between beeps |
| _ALERT_TONE_TAIL_PAUSE | 0.3 s | Silence after the last beep |

Function: radio_dispatch._generate_priority_alert(output_path, sample_rate, codec) -> bool
Generated via ffmpeg lavfi sine source. Non-fatal if generation fails.
Inserted in the concat list after the channel intro and before the first segment.
Mimics MDC-1200 emergency alert tones on real police radio.

### 25d: Chatter Snippets Start Mid-Word (Intentional Design)

RANDOM_CHATTER entries in radio_dispatch.py intentionally start mid-word
(e.g. "clear on Oak Avenue. Resuming patrol.", "ther action needed. Ten eight.").
This is not a bug -- it simulates the user tuning into a radio channel
mid-transmission, creating a realistic tail-end-of-another-call effect.

The strings are used verbatim via normalize_dispatch_text(random.choice(RANDOM_CHATTER)).
No word-boundary truncation logic is applied; the truncation is intentional design.

---

## Section 26: AI Prompt Enhancements (added 2026-03-28)

### 26a: Dispatch Prompts -- Carried Items and Notable Actions

DISPATCH_STAGE2_PROMPT in voxwatch/ai_vision/prompts.py was updated to
explicitly request carried items and notable actions in the suspect description.

| Prompt field | Updated instruction |
|--------------|---------------------|
| description schema comment | "sex, age-range, clothing, build, and any carried items or notable actions" |
| Explicit examples added | "carrying backpack, looking in windows", "bags, tools, weapons", "trying doors, crouching" |
| Example string updated | "male, dark hoodie, gray pants, medium build, carrying backpack, looking in windows" |

Same additions applied to voxwatch/modes/builtin_modes.py for the
police_dispatch built-in mode stage2 template.

### 26b: Gemini maxOutputTokens Increased 300 to 500

maxOutputTokens in both Gemini provider request bodies was increased from 300
to 500 to prevent JSON truncation when AI descriptions include carried items.

| Location | Line (approx) | Previous value | New value |
|----------|---------------|----------------|-----------|
| voxwatch/ai_vision/providers/gemini.py (non-video path) | ~97 | 300 | 500 |
| voxwatch/ai_vision/providers/gemini.py (video path) | ~317 | 300 | 500 |

A MAX_TOKENS finish reason warning was also added at line ~150:
"Gemini response truncated (finishReason=MAX_TOKENS) -- increase maxOutputTokens if this happens frequently"

This log line fires when Gemini signals it stopped due to token limit, not a
content safety block.

---

## Section 27: Frontend Fixes (added 2026-03-28)

### 27a: Setup Wizard Redirect Fix -- React Query Cache Invalidation

Bug: After the setup wizard wrote config.yaml and navigated to /, the
SetupGuard immediately redirected back to /setup because its cached
setup-status query still held config_exists=false.

Fix: ReviewStep.tsx now calls
queryClient.invalidateQueries({ queryKey: ["setup-status"] }) before
navigate("/"). This forces the SetupGuard to re-fetch and see config_exists=true.

| Item | Detail |
|------|--------|
| File | dashboard/frontend/src/components/setup/steps/ReviewStep.tsx |
| When triggered | countdown === 0 (just before navigation) |
| Query key invalidated | ["setup-status"] |
| Effect | SetupGuard re-fetches /api/setup/status before rendering / |

### 27b: MQTT Simulation API Call Fix -- Removed Double /api/ Prefix

Bug: The MQTT simulation button in TestsPage.tsx called
/api/system/mqtt-simulation via an axios client that already prefixes /api/,
resulting in a double-prefix 404.

Fix: The call was changed to /system/mqtt-simulation (no /api/ prefix),
matching how all other API calls in the page use the client.

| Item | Detail |
|------|--------|
| File | dashboard/frontend/src/pages/TestsPage.tsx |
| Correct path passed to client | /system/mqtt-simulation |
| Axios client behavior | Prepends /api/ automatically |

---

## Section 28: Deployment and Infrastructure Changes (added 2026-03-28)

### 28a: GHCR Image Publishing -- GitHub Actions Workflow

New workflow: .github/workflows/docker-publish.yml

| Item | Detail |
|------|--------|
| Trigger | Push to main branch or published release |
| Registry | ghcr.io (GitHub Container Registry) |
| Images built | ghcr.io/badbread/voxwatch and ghcr.io/badbread/voxwatch-dashboard |
| Tag strategy | :latest on main, :version on semver release, :sha on every push |
| Auth | secrets.GITHUB_TOKEN (no personal token required) |
| Build cache | Docker Buildx with GHA cache (type=gha,mode=max) |
| Dashboard context | dashboard/ subdirectory |
| Core service context | Repo root . |

### 28b: docker-compose.yml -- Pull from GHCR

docker-compose.yml updated to reference GHCR images instead of local builds.

| Service | Image |
|---------|-------|
| VoxWatch core | ghcr.io/badbread/voxwatch:latest |
| VoxWatch dashboard | ghcr.io/badbread/voxwatch-dashboard:latest |

Enables one-command install: users run docker compose up -d without building
locally. Images are rebuilt and pushed automatically on every commit to main.

### 28c: README Screenshots Added

Two screenshots added to docs/images/ and embedded in README.md:

| File | Content |
|------|---------|
| docs/images/dashboard.png | Dashboard view showing recent detections with expanded event detail |
| docs/images/pipeline.png | Pipeline configuration tab showing three-stage detection flow with toggles |

Screenshots placed in README after the Quick Start section, before How It Works.

---

## Section 29: QA Audit Log (2026-03-28 v1.6 audit)

### Build Verification Results

| Check | Result |
|-------|--------|
| python -m ruff check voxwatch/ | PASS -- All checks passed, zero lint errors |
| cd dashboard/frontend && npx tsc --noEmit | PASS -- Zero TypeScript type errors |

### New Sections Added This Audit

| Section | Content |
|---------|---------|
| 24 | False positive detection: AI all-unknown escalation skip with MQTT error publish |
| 25a | Stage 1 direct warning for dispatch modes (global TTS, not dispatcher voice) |
| 25b | Dispatch escalation stage_label="stage2" fix (was incorrectly using stage3 schema) |
| 25c | Priority alert tone: three ascending beeps (1000/1200/1400 Hz) before dispatch segments |
| 25d | Chatter snippets: intentional mid-word start simulates radio channel tune-in |
| 26a | AI prompt additions: carried items and notable actions in dispatch description field |
| 26b | Gemini maxOutputTokens 300 to 500 with MAX_TOKENS truncation warning log |
| 27a | Setup wizard redirect fix: invalidate setup-status query before navigate("/") |
| 27b | MQTT simulation double /api/ prefix fix in TestsPage.tsx |
| 28a | GHCR GitHub Actions workflow for automated Docker image publishing |
| 28b | docker-compose.yml updated to reference GHCR images (one-command install) |
| 28c | README screenshots: dashboard.png and pipeline.png added to docs/images/ |

### All Previous Sections Confirmed Unchanged

Sections 1-23 were not modified this audit. No regressions introduced.
Build verification clean on both Python (ruff) and TypeScript (tsc).

---

*Generated: 2026-03-28 | Version: 1.6 | Session audit: dispatch fixes, false positive guard, GHCR publishing*


---

## Section 30: Camera Zones (added 2026-03-29)

### Data Model: ZoneConfig (dashboard/backend/models/config_models.py)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| cameras | list[str] | required | Camera names in this zone |
| speaker | str | required | Which camera speaker plays audio when any zone camera triggers |
| cooldown_seconds | int or None | None | Zone-level cooldown override; falls back to global when None |

Validation: speaker_must_be_in_cameras model validator enforces that the speaker value is present in the cameras list. Raises ValueError if not.

Top-level config field: zones: dict[str, ZoneConfig] | None on VoxWatchConfig. None means no zones configured.

### Service: _resolve_zone() (voxwatch/voxwatch_service.py)

Signature: _resolve_zone(camera_name: str) -> tuple[str | None, dict | None]

Scans self.config["zones"] dict. Returns the first zone name and config dict whose cameras list contains camera_name. Returns (None, None) if not found or zones key is missing.

### Zone Cooldown Keying

When a camera is in a zone, the cooldown shared-state key is "zone:{zone_name}" (e.g. "zone:front_yard"). Non-zone cameras use the camera name as the key. All cameras in the same zone share a single cooldown slot.

Cooldown seconds resolution for zone cameras:
1. zone_cfg["cooldown_seconds"] (when set, non-None)
2. conditions["cooldown_seconds"] (global fallback, default 60)

### Zone Speaker Routing (voxwatch_service.py)

When a zone is resolved: speaker_name = zone_cfg.get("speaker", camera_name). Speaker camera CameraConfig is loaded to get its go2rtc stream. Audio push targets that stream, not the triggering camera stream.

When no zone: audio_output = camera_cfg.get("audio_output", "").strip(); camera_stream = audio_output or camera_cfg.get("go2rtc_stream", camera_name).

### Frontend: Camera Zones Tab (ConfigEditor.tsx)

New tab added: { id: zones, label: Camera Zones, icon: MapPin, section: conditions }

Updated tab order (7 tabs): 1. Personality, 2. TTS, 3. Detection, 4. Camera Zones (new), 5. Pipeline, 6. AI Provider, 7. Connections

### Frontend: ZonesConfigForm Component

File: dashboard/frontend/src/components/config/ZonesConfigForm.tsx

| Behavior | Detail |
|----------|--------|
| Empty state | Dashed border card with MapPin icon; "No zones configured. Cameras operate independently." |
| Add zone | Text input + Add Zone button. Name lowercased, spaces -> underscores. Duplicate names blocked. |
| Zone card | Zone name, camera count, camera chip list (with remove buttons), speaker dropdown, cooldown input |
| Camera assignment | Dropdown shows unassigned cameras plus cameras already in this zone. A camera cannot be in multiple zones. |
| Speaker auto-set | First camera added to a zone is automatically set as the speaker. |
| Speaker cleared | If speaker camera chip removed, speaker resets to first remaining camera or empty string. |
| Cooldown field | Number input (min 10, max 600, step 10). Empty removes override (falls back to global). |
| Zone removal | Delete button. When last zone removed, onChange(undefined) clears the zones key from config. |

Props: zones: Record<string, ZoneConfig> | undefined, cameras: Record<string, CameraConfig>, onChange: (zones | undefined) => void

---

## Section 31: Per-Camera Schedules (added 2026-03-29)

### Data Model: CameraSchedule (dashboard/backend/models/config_models.py)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| mode | str | always | always, scheduled, or sunset_sunrise |
| start | str | 22:00 | Start time HH:MM (scheduled mode only) |
| end | str | 06:00 | End time HH:MM (scheduled mode only) |
| sunset_offset_minutes | int | 0 | Offset from sunset in minutes; negative = before sunset |
| sunrise_offset_minutes | int | 0 | Offset from sunrise in minutes; positive = after sunrise |

CameraSchedule is an optional sub-object on CameraConfig.schedule (default None). When None, the camera uses the global conditions.active_hours setting.

### Service: is_camera_active() (voxwatch/conditions.py)

Signature: is_camera_active(config, camera_name, _logger) -> bool

Priority: per-camera schedule > global active_hours.

| Condition | Behavior |
|-----------|----------|
| camera_cfg.schedule is None/absent | Falls back to is_active_hours(config) (global) |
| mode == always | Returns True (24/7) |
| mode == scheduled | Delegates to is_within_window(start, end) |
| mode == sunset_sunrise | Delegates to is_between_sunset_and_sunrise(config, sunset_offset_minutes, sunrise_offset_minutes) |
| Unknown mode | Logs warning, defaults to True (safe -- never silently suppresses events) |

### City-Based Sunset Lookup (voxwatch/conditions.py)

_resolve_coordinates(conditions) priority chain:
1. conditions.city -- name string looked up via astral.geocoder.lookup(). Returns lat/lon from the geocoder database.
2. conditions.latitude + conditions.longitude -- explicit coordinate pair.
3. San Francisco default coordinates -- hardcoded fallback.

When astral.geocoder raises any exception on a city lookup, a warning is logged and the fallback is used. conditions.city is a convenience alias for common city names in the astral built-in database.

### Frontend: Detection Tab -- Per-Camera Schedule Rows

File: dashboard/frontend/src/components/config/ConditionsConfigForm.tsx

CameraScheduleRow component: one row per configured camera in the Detection tab.

| Mode selection | Result |
|---------------|--------|
| global | Removes schedule key from that camera config (falls back to global) |
| always | Sets schedule: { mode: always } |
| scheduled | Sets schedule with mode, start, end and inline time inputs |
| sunset_sunrise | Sets schedule with mode and offset number inputs |

### Frontend: Camera Card Schedule Display (CameraStatusCard.tsx)

The footer row of each camera card shows a schedule label from the per-camera schedule if present, otherwise from global conditions.active_hours:

| Schedule source | Label shown |
|-----------------|-------------|
| Per-camera mode always | 24/7 |
| Per-camera mode scheduled | {start} - {end} (e.g. 22:00 - 06:00) |
| Per-camera mode sunset_sunrise | Sunset - Sunrise |
| No per-camera schedule | Global active_hours label via formatScheduleLabel() |

---

## Section 32: Persistent Deterrence -- Stage 3 (added 2026-03-29)

### Config Fields (voxwatch/config.py _apply_defaults)

Config path: pipeline.persistent_deterrence

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | false | Enable persistent deterrence loop |
| delay_seconds | float | 30 | Seconds to wait between each deterrence iteration |
| max_iterations | int | 5 | Maximum number of loop iterations |
| alarm_tone | str | none | Tone played between iterations: none, brief, continuous |
| describe_actions | bool | true | Generate fresh AI description each iteration; false uses canned messages |
| escalation_tone | str | increasing | steady (same tone) or increasing (escalates across iterations) |
| tone_levels | list[str] | 3-item default list | Custom AI tone instruction strings per escalation tier |

Default tone_levels when not configured:
- Tone: firm and direct.
- Tone: stern and urgent.
- Tone: very serious, final warning energy.

### Service: _run_persistent_deterrence() (voxwatch/voxwatch_service.py)

Signature: async _run_persistent_deterrence(event_id, camera_name, camera_stream, mode_name, last_description, voice_config, persist_cfg, pipeline_start_ts, vw_event_id) -> int

Returns the number of iterations completed with audio. Called from _handle_detection() after successful escalation when pipeline.persistent_deterrence.enabled is True.

Trigger condition: _escalation_ran=True AND _escalation_audio_success=True

Loop behavior per iteration:
1. asyncio.sleep(delay_seconds) -- waits before acting.
2. check_person_still_present() -- presence check via Frigate snapshots. Breaks loop if person left.
3. If describe_actions=True: fetches fresh AI description; includes elapsed time since detection start for context.
4. If describe_actions=False: uses canned deterrence messages.
5. Applies tone level: when escalation_tone == increasing, selects a tone from tone_levels distributed evenly across max_iterations. Appended as suffix to the AI base prompt.
6. Pushes audio to camera_stream.
7. Publishes MQTT stage event.

Result logged in events.jsonl as persistent_deterrence_iterations: N.

### TypeScript Interface: PipelinePersistentDeterrence (dashboard/frontend/src/types/config.ts)

Fields: enabled: boolean, delay_seconds: number, max_iterations: number, alarm_tone: none|brief|continuous, describe_actions: boolean, escalation_tone: steady|increasing, tone_levels?: string[]

Added to PipelineConfig.persistent_deterrence?: PipelinePersistentDeterrence.

### Frontend: Pipeline Tab -- Persistent Deterrence Card (StagesConfigForm.tsx)

Stage card ID: persistent_deterrence. Rendered in the Pipeline tab between Escalation and Resolution.

UI controls: enable/disable toggle, delay between warnings (seconds), max iterations, alarm tone (none/brief/continuous), describe actions checkbox, escalation tone (steady/increasing), tone levels editable list (shown only when escalation_tone == increasing).

---

## Section 33: Per-Camera Audio Output Override (added 2026-03-29)

### Config Field: audio_output (CameraConfig)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| audio_output | str or None | None | Override speaker for this camera detections. Set to another camera go2rtc stream name. |

When set, audio from this camera detections is routed to the audio_output stream instead of the camera own stream. Value is stripped of whitespace; empty string is treated as unset.

Audio output resolution order (non-zone cameras):
1. camera_cfg["audio_output"] if non-empty after strip
2. camera_cfg["go2rtc_stream"] if set
3. Camera name as fallback stream name

### Frontend: Audio Output Speaker Dropdown (CameraDetail.tsx)

Location: Camera detail panel (Cameras page), after the go2rtc stream name field.

- select populated with all other configured camera names (not the current camera).
- Default option: Same camera (default) maps to empty string.
- On change: writes audio_output to the camera draft config.
- Helper text: Which camera speaker plays audio when this camera detects someone.


---

## Section 34: Dashboard Redesign (added 2026-03-29)

### DashboardPage Layout (dashboard/frontend/src/pages/DashboardPage.tsx)

Redesigned from a config-heavy admin panel into a reactive status-first layout.

| Section | Component | Description |
|---------|-----------|-------------|
| 1. System Hero | ServiceStatusCard | Full-width status card with pulsing dot, headline, stat row, most-recent detection |
| 2. Camera Grid | CameraStatusGrid | VoxWatch-enabled cameras only; clicking navigates to /cameras?selected={name} |
| 3. Recent Activity | RecentActivity | Stacked detection event feed |
| 4. Support Footer | SupportCard | Minimal single-line coffee link |

Changes from previous dashboard:
- Quick Actions section removed entirely (QuickActions component no longer rendered in DashboardPage)
- Camera grid filtered to VoxWatch-enabled cameras only (not all Frigate cameras)
- Support footer is minimal single-line (not a full card block)
- No new API calls -- all data flows from useServiceStatus() and useConfigQuery() shared polling


---

## Section 35: Security Cleanup (added 2026-03-29)

### CI Workflow: .github/workflows/ci.yml

The credential scan step uses a regex pattern to detect literal password assignments. No hardcoded passwords or MQTT credentials remain in the CI workflow file itself.

### Documentation Sanitization

Camera layout references and credential examples in documentation were reviewed. No literal credentials remain in committed docs. All config examples use ${ENV_VAR} token substitution patterns.


---

## Section 36: Setup Wizard Redirect Fix Re-Confirmed (2026-03-29)

Originally documented in Section 27a (v1.6 audit). Behavior confirmed unchanged.

File: dashboard/frontend/src/components/setup/steps/ReviewStep.tsx

After POST /api/setup/generate-config succeeds and the countdown reaches 0, queryClient.invalidateQueries({ queryKey: ["setup-status"] }) is called before navigate("/"). This forces SetupGuard to re-fetch /api/setup/status and see config_exists=true, preventing an immediate redirect back to /setup.

---

## Section 37: QA Audit Log (2026-03-29 v1.7 audit)

### Build Verification Results

| Check | Result |
|-------|--------|
| python -m ruff check voxwatch/ | PASS -- All checks passed, zero lint errors |
| cd dashboard/frontend && npx tsc --noEmit | PASS -- Zero TypeScript type errors |

### New Sections Added This Audit

| Section | Content |
|---------|---------|
| 30 | Camera Zones: ZoneConfig model, _resolve_zone(), zone cooldown keying (zone:{name}), speaker routing, Camera Zones tab (7th tab), ZonesConfigForm component |
| 31 | Per-camera schedules: CameraSchedule model, is_camera_active(), city-based sunset lookup, Detection tab schedule rows, camera card schedule display logic |
| 32 | Persistent Deterrence Stage 3: _run_persistent_deterrence() loop, configurable tone_levels, alarm_tone, PipelinePersistentDeterrence TypeScript type, Pipeline tab card |
| 33 | Per-camera audio output: audio_output CameraConfig field, Audio Output Speaker dropdown in CameraDetail |
| 34 | Dashboard redesign: VoxWatch-only camera grid, Quick Actions removed, minimal support footer, four-section layout |
| 35 | Security cleanup: CI credential scan pattern hardening, docs sanitization |
| 36 | Setup wizard redirect fix re-confirmed (Section 27a original) |

### All Previous Sections Confirmed Unchanged

Sections 1-29 were not modified this audit. No regressions introduced.
Build verification clean on both Python (ruff) and TypeScript (tsc).

---

*Generated: 2026-03-29 | Version: 1.7 | Session audit: zones, per-camera schedules, persistent deterrence, audio output override, dashboard redesign*
