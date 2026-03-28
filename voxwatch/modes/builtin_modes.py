"""builtin_modes.py — Static built-in response mode definitions for VoxWatch.

Contains all 12 built-in :class:`~voxwatch.modes.mode.ResponseMode` objects
that are always available regardless of config.yaml content.  User-defined
modes in config.yaml are layered on top by the loader; built-in modes act as
the fallback library.

The ``_stage`` and ``_mode`` helper constructors live here because they are
only used to build this list.  ``loader.py`` imports the finished
``BUILTIN_MODES`` list rather than re-constructing modes at load time.

Public names
------------
``BUILTIN_MODES`` — ``list[ResponseMode]`` — all built-in modes in display order.
"""

from __future__ import annotations

from voxwatch.modes.mode import (
    BehaviorConfig,
    ResponseMode,
    StageConfig,
    ToneConfig,
    VoiceConfig,
)

# ── Convenience constructors ──────────────────────────────────────────────────


def _stage(
    prompt_modifier: str,
    templates: list[str],
) -> StageConfig:
    """Convenience constructor for a StageConfig.

    Args:
        prompt_modifier: System-role instruction to prepend to the AI prompt.
        templates: Ordered list of fallback template strings.

    Returns:
        A populated :class:`~voxwatch.modes.mode.StageConfig`.
    """
    return StageConfig(prompt_modifier=prompt_modifier, templates=templates)


def _mode(
    id: str,
    category: str,
    name: str,
    description: str,
    effect: str,
    stages: dict[str, StageConfig],
    *,
    tone: ToneConfig | None = None,
    voice: VoiceConfig | None = None,
    behavior: BehaviorConfig | None = None,
) -> ResponseMode:
    """Convenience constructor for a ResponseMode.

    Args:
        id: Unique mode identifier string.
        category: Category label — one of ``"core"``, ``"advanced"``,
            ``"novelty"``, or ``"custom"``.
        name: Human-readable display name.
        description: One-line description for the UI.
        effect: Short psychological-effect label.
        stages: Dict mapping stage keys to StageConfig instances.
        tone: Optional ToneConfig; defaults to plain ToneConfig().
        voice: Optional VoiceConfig; defaults to plain VoiceConfig().
        behavior: Optional BehaviorConfig; defaults to plain BehaviorConfig().

    Returns:
        A fully populated :class:`~voxwatch.modes.mode.ResponseMode`.
    """
    return ResponseMode(
        id=id,
        category=category,
        name=name,
        description=description,
        effect=effect,
        tone=tone or ToneConfig(),
        voice=voice or VoiceConfig(),
        behavior=behavior or BehaviorConfig(),
        stages=stages,
    )


# ---------------------------------------------------------------------------
# Built-in mode library
# ---------------------------------------------------------------------------
# These 12 modes are always available regardless of config.yaml content.
# User-defined modes in config.yaml are layered on top; they can override
# a built-in by using the same ``id``.
# ---------------------------------------------------------------------------

BUILTIN_MODES: list[ResponseMode] = [

    # ── Core Modes ───────────────────────────────────────────────────────────

    _mode(
        id="police_dispatch",
        category="core",
        name="Police Dispatch",
        description=(
            "Multi-voice radio simulation. Sounds like a real dispatch center "
            "is routing police to your address."
        ),
        effect="Sounds like a real dispatch center routing police to your address",
        behavior=BehaviorConfig(
            is_dispatch=True,
            use_radio_effect=True,
            officer_response=True,
            json_ai_output=True,
            scene_context_prefix=True,
        ),
        tone=ToneConfig(mood="authoritative", speed_multiplier=0.9, radio_effect=True),
        voice=VoiceConfig(kokoro_voice="af_bella", openai_voice="nova", elevenlabs_voice="46zEzba8Y8yQ0bVcv5O9"),
        stages={
            "stage1": _stage(
                prompt_modifier=(
                    "You are a female police dispatcher on a radio channel. "
                    "Speak in police radio dispatch language — 10-codes, calm "
                    "professional tone, concise and factual."
                ),
                templates=[
                    "All units... be advised. Subject detected at {address_street}.",
                    "{camera_name} dispatch... 10-97 at {address_street}. Subject detected.",
                    "All units... 10-97. Unauthorized subject on premises.",
                ],
            ),
            "stage2": _stage(
                prompt_modifier=(
                    "You are a police dispatcher receiving a camera feed report. "
                    "Respond with ONLY a JSON object — no markdown fences, no preamble. "
                    "Use short, factual dispatch language.\n\n"
                    "Required JSON schema:\n"
                    "{\n"
                    '  "suspect_count": "one" | "two" | "multiple",\n'
                    '  "description": "sex, age-range, clothing top-to-bottom, build",\n'
                    '  "location": "where they are relative to the property"\n'
                    "}\n\n"
                    "Rules:\n"
                    "- description: comma-separated fragments, no full sentences. "
                    'Example: "male, dark hoodie, gray pants, medium build"\n'
                    "- location: one short clause. "
                    'Example: "approaching front door from driveway"\n'
                    "- If night vision (grayscale/green): skip colors, describe silhouette "
                    "and clothing type instead.\n"
                    "- All fields required. Use \"unknown\" if truly indeterminate.\n"
                    "- Respond with ONLY the JSON object, nothing else."
                ),
                templates=[
                    "Dispatch... {suspect_count} subject. {clothing_description}. "
                    "{location_on_property}.",
                    "All units... suspect described as {clothing_description} at "
                    "{location_on_property}.",
                ],
            ),
            "stage3": _stage(
                prompt_modifier=(
                    "You are a police dispatcher receiving a live camera update. "
                    "Respond with ONLY a JSON object — no markdown fences, no preamble. "
                    "Use short, factual dispatch language.\n\n"
                    "Required JSON schema:\n"
                    "{\n"
                    '  "behavior": "what the suspect is actively doing right now",\n'
                    '  "movement": "how the suspect has moved since last report"\n'
                    "}\n\n"
                    "Rules:\n"
                    "- behavior: comma-separated active-voice fragments. "
                    'Example: "testing gate latch, looking over shoulder toward street"\n'
                    "- movement: one short clause describing position change. "
                    'Example: "moved from driveway to side gate"\n'
                    "- If no clear movement, set movement to \"stationary\".\n"
                    "- If night vision (grayscale/green): focus on actions, not colors.\n"
                    "- All fields required. Use \"unknown\" if truly indeterminate.\n"
                    "- Respond with ONLY the JSON object, nothing else."
                ),
                templates=[
                    "Dispatch update. Suspect {behavior_description} at {location_on_property}. "
                    "Advise immediate departure.",
                    "Update: subject still on premises. {behavior_description}. "
                    "Respond code three.",
                ],
            ),
        },
    ),

    _mode(
        id="live_operator",
        category="core",
        name="Live Operator",
        description=(
            "Sounds like a real person is actively watching the camera feed right now. "
            "Personal, direct, and specific."
        ),
        effect="Makes the subject feel personally watched by a real human",
        tone=ToneConfig(mood="watchful", speed_multiplier=1.0),
        voice=VoiceConfig(kokoro_voice="am_michael", openai_voice="onyx", elevenlabs_voice="ErXwobaYiN019PkySvjV"),
        stages={
            "stage1": _stage(
                prompt_modifier="",
                templates=[
                    "I can see you right now. Step away from the property.",
                    "Hey. I'm watching this feed live. You need to leave.",
                    "I can see you on camera. Walk away now.",
                ],
            ),
            "stage2": _stage(
                prompt_modifier=(
                    "You are a live human operator watching this camera feed right now. "
                    "Speak directly and personally — you can see the person in real time. "
                    "Be calm but absolutely firm. Short sentences only. "
                    "Make them feel like a real person is watching them specifically. "
                    "Reference what they are wearing or doing. Address them directly with 'you'. "
                    "Return a JSON array of 1-2 short phrases (under 15 words each) that "
                    "will be read aloud in sequence for natural cadence. "
                    'Example: ["I can see your {clothing_description}.", "You need to leave now."]'
                ),
                templates=[
                    "I can see you — {clothing_description}. You need to leave right now.",
                    "I'm watching you at {location_on_property}. I can see everything. Leave.",
                ],
            ),
            "stage3": _stage(
                prompt_modifier=(
                    "You are a live operator who has been watching this person for several "
                    "seconds. You know exactly what they are doing. Be specific about their "
                    "actions. Short, direct, calm but serious. "
                    "Return a JSON array of 1-2 short phrases (under 15 words each). "
                    'Example: ["I see what you\'re doing at that gate.", "I\'ve already called."]'
                ),
                templates=[
                    "I can see you {behavior_description}. I've already made the call.",
                    "Still watching you at {location_on_property}. Leave before this gets worse.",
                ],
            ),
        },
    ),

    _mode(
        id="private_security",
        category="core",
        name="Private Security",
        description=(
            "Professional corporate security firm voice. Firm, formal, no-nonsense. "
            "Implies a staffed monitoring center."
        ),
        effect="Projects professional authority — implies staffed monitoring",
        tone=ToneConfig(mood="authoritative", speed_multiplier=0.95),
        voice=VoiceConfig(kokoro_voice="am_fenrir", openai_voice="echo", elevenlabs_voice="pNInz6obpgDQGcFmaJgB"),
        stages={
            "stage1": _stage(
                prompt_modifier="",
                templates=[
                    "Attention. You are on private property under active surveillance.",
                    "This is a private security notice. You have been detected on restricted property.",
                    "Security alert. You are on private property. Vacate immediately.",
                ],
            ),
            "stage2": _stage(
                prompt_modifier=(
                    "You are a professional private security officer. Be firm, formal, and direct. "
                    "No threats — just absolute authority. Use professional security language. "
                    "Make it clear this is private property under active monitoring. "
                    "Reference the subject's specific appearance to show they have been identified. "
                    "Return a JSON array of 1-2 short phrases (under 20 words each). "
                    'Example: ["Individual in {clothing_description} — you have been identified.", '
                    '"Vacate the premises immediately."]'
                ),
                templates=[
                    "Individual in {clothing_description} at {location_on_property} — "
                    "you have been identified. Vacate immediately.",
                    "Security alert: subject detected at {location_on_property}. "
                    "This incident is being logged. Leave the property now.",
                ],
            ),
            "stage3": _stage(
                prompt_modifier=(
                    "You are a private security officer observing continued unauthorized presence. "
                    "Escalate authority — make it clear that law enforcement is being contacted. "
                    "Reference the subject's specific behavior. Formal, professional, final warning. "
                    "Return a JSON array of 1-2 short phrases (under 20 words each)."
                ),
                templates=[
                    "You have been observed {behavior_description} at {location_on_property}. "
                    "Authorities have been contacted. Leave now.",
                    "Final warning. Subject {behavior_description} — law enforcement notified. "
                    "Vacate the premises.",
                ],
            ),
        },
    ),

    _mode(
        id="homeowner",
        category="core",
        name="Homeowner",
        description=(
            "Direct personal voice — sounds like the property owner is speaking "
            "through their own system."
        ),
        effect="Personal and direct — sounds like you're home and watching",
        tone=ToneConfig(mood="firm", speed_multiplier=1.0),
        voice=VoiceConfig(kokoro_voice="af_heart", openai_voice="nova"),
        stages={
            "stage1": _stage(
                prompt_modifier="",
                templates=[
                    "Hey. I can see you. Please leave my property.",
                    "I can see you on my cameras. You need to go.",
                    "This is private property. I'm watching. Leave now.",
                ],
            ),
            "stage2": _stage(
                prompt_modifier=(
                    "You are the homeowner speaking through your security system. "
                    "Be personal, direct, and clear — not aggressive, but unmistakably serious. "
                    "You can see them. You know what they are wearing. "
                    "Use conversational language. Address them as 'you'. "
                    "Return a JSON array of 1-2 short conversational phrases (under 15 words each). "
                    'Example: ["I can see you in that {clothing_description}.", "Please leave now."]'
                ),
                templates=[
                    "I can see you — {clothing_description}. Please leave my property.",
                    "Hey. I see you at {location_on_property}. I'm calling the police right now.",
                ],
            ),
            "stage3": _stage(
                prompt_modifier=(
                    "You are the homeowner watching your cameras. The person has not left. "
                    "You are now more serious. Make it clear you are calling police. "
                    "Reference what they are doing specifically. Short, direct, calm but firm. "
                    "Return a JSON array of 1-2 phrases (under 15 words each)."
                ),
                templates=[
                    "I said leave. I can see you {behavior_description}. Police are on the way.",
                    "Still here at {location_on_property}? I've already called. Last chance.",
                ],
            ),
        },
    ),

    _mode(
        id="evidence_collection",
        category="core",
        name="Evidence Collection",
        description=(
            "Cold, clinical automated logging system. No emotion, no threats — "
            "just the icy certainty that everything is being permanently recorded."
        ),
        effect="The chill of a system that records everything without judgment",
        tone=ToneConfig(mood="cold", speed_multiplier=0.9),
        voice=VoiceConfig(kokoro_voice="af_kore", openai_voice="alloy"),
        stages={
            "stage1": _stage(
                prompt_modifier="",
                templates=[
                    "Recording initiated. Unauthorized subject logged. Entry attempt documented.",
                    "Evidence capture active. Subject detected. Timestamp recorded.",
                    "Automated alert: unauthorized presence detected and logged.",
                ],
            ),
            "stage2": _stage(
                prompt_modifier=(
                    "You are an automated evidence-logging system. "
                    "Speak in cold, clinical, system-driven language. No emotion, no threats. "
                    "State facts: what was observed, that it has been recorded, transmitted. "
                    "Reference the time, the camera, and the subject's appearance factually. "
                    "Return a JSON array of 1-2 short clinical phrases (under 20 words each). "
                    'Example: ["Subject recorded: {clothing_description}. Timestamp logged.", '
                    '"Data transmitted to {camera_name} archive."]'
                ),
                templates=[
                    "Subject recorded: {clothing_description} at {location_on_property}. "
                    "Timestamp logged. Data transmitted.",
                    "Evidence capture: {suspect_count} subject at {camera_name}. "
                    "Biometric data being processed.",
                ],
            ),
            "stage3": _stage(
                prompt_modifier=(
                    "You are an automated evidence system logging continued unauthorized presence. "
                    "State what the subject is doing factually and clinically. "
                    "Reference that all behavior is being documented. Cold, final, certain. "
                    "Return a JSON array of 1-2 short clinical phrases (under 20 words each)."
                ),
                templates=[
                    "Continued recording: subject {behavior_description}. "
                    "All activity documented for law enforcement.",
                    "Behavioral log updated: {behavior_description} at {location_on_property}. "
                    "File transmitted.",
                ],
            ),
        },
    ),

    # ── Advanced Modes ───────────────────────────────────────────────────────

    _mode(
        id="silent_pressure",
        category="advanced",
        name="Silent Pressure",
        description=(
            "Minimum words, maximum tension. Implies total awareness without "
            "explaining anything. The silence between the words does the work."
        ),
        effect="Unsettling certainty — they know you know",
        tone=ToneConfig(mood="menacing", speed_multiplier=0.85),
        voice=VoiceConfig(kokoro_voice="am_onyx", openai_voice="onyx"),
        stages={
            "stage1": _stage(
                prompt_modifier="",
                templates=[
                    "We see you.",
                    "Noted.",
                    "Stop.",
                ],
            ),
            "stage2": _stage(
                prompt_modifier=(
                    "You are a presence that knows everything and says almost nothing. "
                    "You see the person clearly. You do not threaten — you simply confirm "
                    "absolute awareness. Minimum words. Maximum weight. "
                    "Two to five words maximum per phrase. Do not explain. Do not elaborate. "
                    "Return a JSON array of 1-2 very short phrases (2-6 words each). "
                    'Example: ["We see you.", "{clothing_description}. Noted."]'
                ),
                templates=[
                    "{clothing_description}. We see you.",
                    "We know. {location_on_property}. Leave.",
                    "Recorded. Leave now.",
                ],
            ),
            "stage3": _stage(
                prompt_modifier=(
                    "You are a presence that has been watching for a while now. "
                    "Still minimum words. Slightly colder. More final. "
                    "The subject should feel that their decision has been made for them. "
                    "Return a JSON array of 1-2 very short phrases (2-6 words each). "
                    'Example: ["Still here.", "Wrong choice."]'
                ),
                templates=[
                    "Still here. Wrong choice.",
                    "Last chance.",
                    "We're done waiting.",
                ],
            ),
        },
    ),

    _mode(
        id="neighborhood_alert",
        category="advanced",
        name="Neighborhood Alert",
        description=(
            "Implies the entire neighborhood is watching and has already been "
            "notified. Social pressure from a community, not just a camera."
        ),
        effect="The whole street is watching — public accountability pressure",
        tone=ToneConfig(mood="communal", speed_multiplier=1.0),
        voice=VoiceConfig(kokoro_voice="af_sarah", openai_voice="shimmer"),
        stages={
            "stage1": _stage(
                prompt_modifier="",
                templates=[
                    "Neighbors have been alerted. This street is being monitored.",
                    "Community alert active. Multiple households have been notified.",
                    "You are being watched by the entire neighborhood right now.",
                ],
            ),
            "stage2": _stage(
                prompt_modifier=(
                    "You are a neighborhood watch coordinator making a community alert. "
                    "Reference that neighbors are watching, the community has been alerted, "
                    "and this activity has already been reported to multiple households. "
                    "Use firm community-authority language — the whole street is aware. "
                    "Reference the subject's appearance so they know they've been identified. "
                    "Return a JSON array of 1-2 short phrases (under 20 words each). "
                    'Example: ["Neighborhood alert: {clothing_description} at {location_on_property}.", '
                    '"Multiple households have been notified."]'
                ),
                templates=[
                    "Neighborhood alert: {clothing_description} spotted at {location_on_property}. "
                    "Multiple households have been notified.",
                    "This street is watching you. {clothing_description} — you have been "
                    "identified by the community.",
                ],
            ),
            "stage3": _stage(
                prompt_modifier=(
                    "You are a neighborhood watch coordinator reporting continued suspicious activity. "
                    "Reference that neighbors have now seen this person and the police have been called. "
                    "Community solidarity language — many people are watching, not just cameras. "
                    "Return a JSON array of 1-2 short phrases (under 20 words each)."
                ),
                templates=[
                    "Multiple neighbors are watching you {behavior_description}. "
                    "Police have been notified.",
                    "The whole street has seen you at {location_on_property}. "
                    "This is your last warning.",
                ],
            ),
        },
    ),

    _mode(
        id="guard_dog",
        category="advanced",
        name="Guard Dog Warning",
        description=(
            "Implies a canine threat without stating it directly. "
            "Casually mentions unfed, restless dogs — lets the implication do the work."
        ),
        effect="Indirect deterrence through implied canine threat",
        tone=ToneConfig(mood="menacing", speed_multiplier=0.95),
        voice=VoiceConfig(kokoro_voice="am_adam", openai_voice="onyx"),
        stages={
            "stage1": _stage(
                prompt_modifier="",
                templates=[
                    "Hey. I can see you on camera. Just so you know, {dog_names} haven't been fed yet today.",
                    "I see you out there. {dog_names} are getting restless. I'd leave if I were you.",
                    "You're on camera. {dog_names} don't like strangers. Your call.",
                ],
            ),
            "stage2": _stage(
                prompt_modifier=(
                    "You are a homeowner who has large, intimidating dogs. "
                    "Mention the dogs naturally as if they're right there with you. "
                    "Do NOT make explicit threats — let the implication do the work. "
                    "Reference what the person looks like so they know they've been seen. "
                    "Use {dog_names} when referring to the dogs. "
                    "Return a JSON array of 1-2 short phrases (under 15 words each) "
                    "that will be read aloud in sequence for natural cadence. "
                    'Example: ["I see you out there in that {clothing_description}.", '
                    '"Just so you know, {dog_names} can smell strangers from inside."]'
                ),
                templates=[
                    "I can see you — {clothing_description}. "
                    "{dog_names} have been pacing all morning. Just saying.",
                    "You at {location_on_property}. Yeah. {dog_names} noticed you too.",
                ],
            ),
            "stage3": _stage(
                prompt_modifier=(
                    "You are a homeowner watching cameras. The person has stayed. "
                    "Your dogs are now at the door, agitated. Still no explicit threats — "
                    "the escalation is all in the dogs' growing restlessness. "
                    "Reference what the person is doing. Use {dog_names} naturally. "
                    "Return a JSON array of 1-2 short phrases (under 15 words each). "
                    'Example: ["Still {behavior_description}? {dog_names} are at the door now.", '
                    '"I\'d really hate to open it."]'
                ),
                templates=[
                    "Still here at {location_on_property}? {dog_names} are at the door. Getting loud.",
                    "I see you {behavior_description}. {dog_names} hear you too. I can't hold them much longer.",
                ],
            ),
        },
    ),

    _mode(
        id="automated_surveillance",
        category="advanced",
        name="Automated Surveillance",
        description=(
            "Neutral AI monitoring system. Detached, clinical, system language. "
            "Implies facial recognition and behavioral analysis."
        ),
        effect="Cold AI certainty — implies biometric logging and analysis",
        tone=ToneConfig(mood="clinical", speed_multiplier=0.9),
        voice=VoiceConfig(kokoro_voice="af_kore", openai_voice="nova"),
        stages={
            "stage1": _stage(
                prompt_modifier="",
                templates=[
                    "Movement detected. Behavior flagged. Identity processing.",
                    "Automated alert: unauthorized subject detected. Behavioral analysis running.",
                    "Surveillance system: subject detected. Logging initiated.",
                ],
            ),
            "stage2": _stage(
                prompt_modifier=(
                    "You are a neutral AI surveillance system. "
                    "Speak in detached, clinical, system language. "
                    "Use terms like 'subject', 'behavior', 'flagged', 'logged', 'processed'. "
                    "Reference specific observed appearance factually as a system would. "
                    "Imply facial recognition and biometric analysis. "
                    "Return a JSON array of 1-2 short phrases (under 20 words each). "
                    'Example: ["Subject identified: {clothing_description}. Identity logged.", '
                    '"Location confirmed: {location_on_property}. Alert transmitted."]'
                ),
                templates=[
                    "Subject identified: {clothing_description}. "
                    "Location logged: {location_on_property}. Alert transmitted.",
                    "Biometric processing: {suspect_count} subject at {camera_name}. "
                    "Behavioral profile updated.",
                ],
            ),
            "stage3": _stage(
                prompt_modifier=(
                    "You are an AI surveillance system logging continued unauthorized presence. "
                    "Reference the subject's actions clinically and factually. "
                    "Imply that their behavior pattern has been analyzed and flagged. "
                    "Detached, system-language, final. "
                    "Return a JSON array of 1-2 short phrases (under 20 words each)."
                ),
                templates=[
                    "Behavioral flag: subject {behavior_description} at {location_on_property}. "
                    "Pattern analysis complete. Authorities notified.",
                    "Continued unauthorized presence logged. "
                    "Subject {behavior_description}. Escalation protocol active.",
                ],
            ),
        },
    ),

    # ── Standard fallback ────────────────────────────────────────────────────

    _mode(
        id="standard",
        category="core",
        name="Standard",
        description=(
            "Generic security system voice. Clinical and direct. "
            "Used as the fallback when an unknown mode is requested."
        ),
        effect="Generic deterrent — always functional, never wrong",
        stages={
            "stage1": _stage(
                prompt_modifier="",
                templates=[
                    "Attention. You are on private property and being recorded.",
                    "Warning. Unauthorized presence detected. You are being recorded.",
                ],
            ),
            "stage2": _stage(
                prompt_modifier=(
                    "You are a security camera AI. Describe the person briefly and directly. "
                    "Address them as 'you'. One clear sentence, under 20 words. "
                    "Return a JSON array with one short phrase."
                ),
                templates=[
                    "{clothing_description} at {location_on_property} — "
                    "you have been identified. Leave immediately.",
                    "Individual detected at {location_on_property}. "
                    "You have been recorded. Authorities are being contacted.",
                ],
            ),
            "stage3": _stage(
                prompt_modifier=(
                    "You are a security system issuing a final escalation warning. "
                    "The person has not left. Reference their current behavior. "
                    "Direct, clinical, final. Return a JSON array with one short phrase."
                ),
                templates=[
                    "You have been observed {behavior_description}. "
                    "Leave immediately. Authorities are being contacted.",
                    "Final warning. {behavior_description} at {location_on_property}. "
                    "All activity recorded and transmitted.",
                ],
            ),
        },
    ),
]
