Title: I made my cameras talk back — they describe intruders and simulate police dispatch in real-time (Frigate + AI)

---

Someone walks up to your property at night. They hear:

> "Attention. You have been spotted on camera. The homeowner has been alerted."

A few seconds later... radio static. The tail end of another call fading out. Three priority alert beeps. Then:

> "All units, 10-97 at [your address]. Suspect described as male, dark hoodie, medium build, carrying backpack. Caller reports subject checking vehicle door handles. Nearest unit respond, code three."

A different voice:

> "Copy dispatch. Baker 3 en route, ETA four minutes."

All of that is generated in real-time based on what the camera actually sees. Different TTS voices for the dispatcher vs the officer. Radio static effects layered on. The AI describes their actual appearance, clothing, what they're carrying, and what they're doing.

It's the difference between a camera recording someone... and a system that makes them feel like they've already been caught.

---

**What it is**

VoxWatch. It hooks into Frigate via MQTT, grabs snapshots when a person is detected, sends them to an AI vision model for analysis, generates speech via TTS, and pushes the audio out through the camera speaker using go2rtc's backchannel API.

There are 10 other built-in response modes too... homeowner ("Hey, I can see you on camera"), private security, live operator, guard dog warning (implies dogs are nearby), neighborhood watch alert, automated surveillance with sci-fi presets (HAL 9000, T-800, GLaDOS, WOPR), and a fully custom mode where you write your own prompt.

**The tech stack**

AI Vision (picks one, processes camera snapshots):
- Google Gemini Flash (recommended... fast + cheap)
- OpenAI GPT-4o
- Anthropic Claude Haiku
- Ollama with LLaVA (fully local, no API costs)

TTS (generates the spoken audio):
- Kokoro (local neural TTS, recommended... near-human quality, free)
- Piper (local, auto-downloads voice models from HuggingFace including a HAL 9000 voice)
- ElevenLabs (cloud, best quality)
- OpenAI TTS (cloud)
- Cartesia Sonic (cloud, lowest latency)
- Amazon Polly (cloud, cheapest)
- espeak-ng (robotic fallback... always available)

**Home Assistant integration**

VoxWatch publishes MQTT events that HA can consume directly:
- `voxwatch/events/detection` ... person detected, pipeline started
- `voxwatch/events/stage` ... each stage fired with AI description
- `voxwatch/events/ended` ... detection complete
- `voxwatch/events/error` ... something failed (TTS, AI, push)
- `voxwatch/status` ... online/offline with LWT

There's also an announce endpoint... HA can push TTS messages to any camera speaker through VoxWatch via MQTT (`voxwatch/announce` topic). So you could set up automations like "when the garage door opens after midnight, announce through the driveway camera." Or flash your outdoor lights red/blue when a detection fires. Trigger sirens. Turn on all the lights to simulate someone being home. Detect, respond, your house reacts.

**The dashboard**

Web-based config UI with a setup wizard that auto-discovers Frigate, MQTT, and your cameras. After setup you get a config editor with live voice preview (hear what each persona sounds like before committing), camera management with ONVIF identification, audio testing, and a recent detections view where you can click any event and see the full pipeline breakdown... what the AI saw, what TTS text was generated, which voice was used, whether audio push succeeded, total latency.

**Setting expectations... this is early alpha**

I'm releasing this now because I want feedback, not because it's polished. You will hit bugs.

Latency is real. Stage 1 (the instant warning) fires in 0-2 seconds because it's pre-cached. But the full AI-analyzed dispatch sequence takes 30-60 seconds end to end... snapshots, AI analysis, multi-segment TTS generation, radio effect processing. I'm actively working on this but it's the nature of chaining multiple AI calls together.

False positives happen. Frigate sometimes detects "persons" that aren't there. VoxWatch has AI validation now... if Gemini looks at the snapshots and can't identify anyone, it skips the escalation. But the initial warning may still fire. Tune your Frigate min_score threshold.

Camera compatibility is the wildcard. Audio backchannel depends on your camera supporting two-way audio via RTSP. I've tested with Reolink CX410, CX420, E1 Zoom, and Dahua IPC-Color4K-T180. It should work with anything go2rtc can push audio to (Amcrest, Hikvision, UniFi, Tapo, etc.) but I haven't tested those myself. There's a camera compatibility report template on GitHub if you want to contribute test results.

**Install**

Grab the `docker-compose.yml` from the repo, deploy it however you normally do... Portainer stack, `docker compose up -d`, whatever. Images are on GHCR so no building required. Open `http://your-host:33344` and the setup wizard handles the rest.

Requirements: Frigate NVR with MQTT, go2rtc, and a camera with two-way audio.

https://github.com/badbread/VoxWatch

**About the build**

Built with Claude Code... fully transparent about that. Every function has thorough docstrings, there's a custom QA agent that runs regression checks against a 1000+ line test baseline before changes go in, CI runs Python linting + TypeScript type checking + Docker builds + security scanning for leaked credentials on every push. The codebase was recently split from a few oversized files into well-organized packages... the goal is for anyone to be able to fork it and understand what's going on.

GPLv3 licensed. Free for personal and open source use.

**Why I built it**

There have been some door-checking incidents around my neighborhood lately and it got me thinking... most security systems just record. What if they actually reacted?

Happy to answer questions. Even "your README is confusing" is useful feedback at this stage.
