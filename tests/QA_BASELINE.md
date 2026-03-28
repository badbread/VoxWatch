# VoxWatch QA Baseline Manifest
# Version: 1.2 | Date: 2026-03-25 | Coverage: All endpoints, components, and behaviors

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

*Generated: 2026-03-25 | Version: 1.2 | Update on any API, component, or config change*

