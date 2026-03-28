"""
camera_db.py — Camera Model Compatibility Database

Maps known camera model strings to their hardware capability profiles,
specifically whether they have a speaker (built-in or RCA out) and what
audio codec the RTSP backchannel uses.

This database is used by the /api/cameras/{name}/identify endpoint to
give users actionable compatibility information for VoxWatch audio deterrent.

Usage::

    from backend.camera_db import match_camera_model

    result = match_camera_model("IPC-T54IR-AS-2.8mm-S3")
    # -> {"manufacturer": "Dahua", "has_speaker": False, "speaker_type": "rca_out", ...}
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Compatibility constants
# ---------------------------------------------------------------------------

#: Camera has a built-in loudspeaker — fully compatible with VoxWatch.
SPEAKER_BUILTIN = "built_in"

#: Camera has an RCA audio output jack but no built-in speaker.
#: Compatible with VoxWatch only if an external speaker is connected.
SPEAKER_RCA_OUT = "rca_out"

#: Camera has no audio output whatsoever — incompatible with VoxWatch.
SPEAKER_NONE = "none"


# ---------------------------------------------------------------------------
# Known camera model database
# ---------------------------------------------------------------------------

#: Mapping of canonical model string -> capability dict.
#: Keys are the shortest unambiguous prefix of the model name (excluding
#: hardware-revision suffixes like "-2.8mm", "-S3", "-ZE", etc.).
#: Values are plain dicts so callers can safely copy and extend them.
KNOWN_CAMERAS: dict[str, dict] = {
    # ── Reolink ───────────────────────────────────────────────────────────────
    "CX410": {
        "manufacturer": "Reolink",
        "has_speaker": True,
        "speaker_type": SPEAKER_BUILTIN,
        "backchannel_codec": "PCMU/8000",
        "tested": True,
        "notes": "Working. Built-in speaker. RTSP backchannel confirmed via go2rtc.",
    },
    "CX420": {
        "manufacturer": "Reolink",
        "has_speaker": True,
        "speaker_type": SPEAKER_BUILTIN,
        "backchannel_codec": "PCMU/8000",
        "tested": True,
        "notes": "Working. Built-in speaker. Same backchannel profile as CX410.",
    },
    "E1 Zoom": {
        "manufacturer": "Reolink",
        "has_speaker": True,
        "speaker_type": SPEAKER_BUILTIN,
        "backchannel_codec": "PCMU/8000",
        "tested": True,
        "notes": (
            "Working. Indoor PTZ camera with built-in speaker. "
            "RTSP backchannel confirmed via go2rtc."
        ),
    },
    # ── Dahua — built-in speaker ─────────────────────────────────────────────
    "IPC-Color4K-T180": {
        "manufacturer": "Dahua",
        "has_speaker": True,
        "speaker_type": SPEAKER_BUILTIN,
        "backchannel_codec": "PCMA/8000",
        "tested": True,
        "notes": (
            "Working. Use Dahua RTSP URL format, not ONVIF. "
            "Built-in speaker confirmed."
        ),
    },
    # ── Dahua — RCA audio output, no built-in speaker ────────────────────────
    "IPC-T54IR-AS": {
        "manufacturer": "Dahua",
        "has_speaker": False,
        "speaker_type": SPEAKER_RCA_OUT,
        "backchannel_codec": "PCMA/8000",
        "tested": True,
        "notes": (
            "No built-in speaker. Has RCA audio output jack — works with "
            "an external passive or powered speaker wired to the RCA port."
        ),
    },
    "IPC-B54IR-ASE": {
        "manufacturer": "Dahua",
        "has_speaker": False,
        "speaker_type": SPEAKER_RCA_OUT,
        "backchannel_codec": "PCMA/8000",
        "tested": True,
        "notes": (
            "No built-in speaker. Has RCA audio output jack — works with "
            "an external speaker. Bullet-form-factor sibling of IPC-T54IR-AS."
        ),
    },
    # ── Dahua — no audio output at all ───────────────────────────────────────
    "IPC-T58IR-ZE": {
        "manufacturer": "Dahua",
        "has_speaker": False,
        "speaker_type": SPEAKER_NONE,
        "backchannel_codec": None,
        "tested": True,
        "notes": (
            "No speaker, no RCA output, no RTSP backchannel. "
            "Incompatible with VoxWatch audio deterrent."
        ),
    },
}


# ---------------------------------------------------------------------------
# Model matching
# ---------------------------------------------------------------------------

def match_camera_model(model_string: str) -> dict | None:
    """Return capability info for a camera given its raw model string.

    Performs fuzzy matching so that full product variant strings such as
    ``"IPC-T54IR-AS-2.8mm-S3"`` correctly resolve to the canonical entry
    ``"IPC-T54IR-AS"``.  The matching strategy is:

    1. Exact match (fastest path, handles perfect hits).
    2. Prefix match — checks whether the raw model string *starts with* a
       known key (handles suffix-only variants like "-2.8mm" or "-ZE").
    3. Contains match — checks whether a known key appears *anywhere* in the
       raw string (handles strings that include brand prefixes or extra text).

    Comparisons are case-insensitive throughout.

    Args:
        model_string: Raw model identifier returned by ONVIF or typed by the
            user.  May contain lens-size suffixes, revision codes, etc.
            Examples: ``"CX410"``, ``"IPC-T54IR-AS-2.8mm-S3"``.

    Returns:
        A copy of the capability dict from KNOWN_CAMERAS with the matched
        ``"model_key"`` field added, or ``None`` if no entry matches.

    Examples::

        >>> match_camera_model("CX410")
        {"manufacturer": "Reolink", "has_speaker": True, ..., "model_key": "CX410"}

        >>> match_camera_model("IPC-T54IR-AS-2.8mm-S3")
        {"manufacturer": "Dahua", "has_speaker": False, "speaker_type": "rca_out", ...}

        >>> match_camera_model("UnknownCam-9000")
        None
    """
    if not model_string:
        return None

    normalised = model_string.strip().upper()

    # Pass 1: exact match
    for key, info in KNOWN_CAMERAS.items():
        if normalised == key.upper():
            return {**info, "model_key": key}

    # Pass 2: raw string starts with the known key (suffix variants)
    for key, info in KNOWN_CAMERAS.items():
        if normalised.startswith(key.upper()):
            return {**info, "model_key": key}

    # Pass 3: known key appears anywhere inside the raw string
    for key, info in KNOWN_CAMERAS.items():
        if key.upper() in normalised:
            return {**info, "model_key": key}

    return None


def list_all_models() -> list[dict]:
    """Return the full compatibility database as a list of dicts.

    Each entry includes the canonical ``"model_key"`` field so callers can
    display or iterate over all known models without needing direct access to
    the ``KNOWN_CAMERAS`` dict.

    Returns:
        List of capability dicts, one per known model, sorted by manufacturer
        then model key.
    """
    return sorted(
        [{**info, "model_key": key} for key, info in KNOWN_CAMERAS.items()],
        key=lambda d: (d.get("manufacturer", ""), d.get("model_key", "")),
    )
