"""conditions.py — Active-hours and cooldown guard functions for VoxWatch.

This module contains all the logic for deciding whether a detection event
should be acted upon at the current moment in time:

  - Active-hours mode dispatch (``is_active_hours``): routes to the correct
    sub-function based on the ``conditions.active_hours.mode`` config key.
  - Sunset/sunrise window (``is_between_sunset_and_sunrise``): uses the
    ``astral`` library to compute solar events at the configured lat/lon.
  - Fixed clock window (``is_in_fixed_window``): handles midnight-crossing
    time ranges expressed as "HH:MM" strings.
  - Per-camera cooldown (``check_cooldown``): prevents repeated triggers on
    the same camera within a configurable window.

All functions are deliberately standalone (no class methods) so they are easy
to unit-test in isolation and can be imported into any future modules that need
the same scheduling logic.

Design note — why monotonic for cooldowns?
    ``time.monotonic()`` is used for cooldown timestamps because it is
    unaffected by wall-clock adjustments (NTP slew, DST transitions, etc.).
    A wall-clock jump forward could falsely expire a cooldown; a jump backward
    could lock a camera out until the clock catches up.
"""

import logging
import time
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from typing import Any

logger = logging.getLogger("voxwatch.conditions")


def is_active_hours(config: dict[str, Any], _logger: logging.Logger = logger) -> bool:
    """Determine whether the service should respond to detections right now.

    Dispatches to the appropriate sub-function based on the
    ``conditions.active_hours.mode`` config key.  Supports three modes:

      - ``"always"``: Always active, 24/7.  Useful for testing or high-security
        properties.
      - ``"sunset_sunrise"``: Active only between sunset and sunrise (nighttime).
        Uses the ``astral`` library with the lat/lon from config.  This is the
        recommended mode for residential use — daytime detections are expected
        and don't warrant an alarm.
      - ``"fixed"``: Active between the literal ``start`` and ``end`` clock
        times in the config (``HH:MM`` format, 24-hour).  Handles midnight
        crossing, e.g. 22:00 – 06:00.

    Unknown modes default to active so that a misconfiguration never silently
    causes detections to be dropped.

    Args:
        config: The full VoxWatch config dict (from ``voxwatch.config.load_config``).
        _logger: Logger to use for warnings.  Defaults to the module logger;
            callers can pass a more specific logger if desired.

    Returns:
        True if the service should act on detections now, False otherwise.
    """
    conditions = config.get("conditions", {})
    active_hours = conditions.get("active_hours", {})
    mode = active_hours.get("mode", "always")

    if mode == "always":
        return True

    if mode == "sunset_sunrise":
        return is_between_sunset_and_sunrise(
            config,
            _logger,
            sunset_offset_minutes=int(conditions.get("sunset_offset_minutes", 0)),
            sunrise_offset_minutes=int(conditions.get("sunrise_offset_minutes", 0)),
        )

    if mode == "fixed":
        return is_in_fixed_window(
            active_hours.get("start", "22:00"),
            active_hours.get("end", "06:00"),
            _logger,
        )

    # Unknown mode — default to active so we don't silently miss events.
    _logger.warning(
        "Unknown active_hours mode '%s' — defaulting to always active.", mode
    )
    return True


def _resolve_location(
    conditions: dict[str, Any],
    _logger: logging.Logger = logger,
) -> "tuple[float, float]":
    """Resolve a (latitude, longitude) pair from multiple config sources.

    Resolution priority:
      1. ``conditions.city`` — looked up via ``astral.geocoder`` if available.
      2. ``conditions.latitude`` + ``conditions.longitude`` — explicit coords.

    Returns the best available coordinates, defaulting to San Francisco
    (37.7749, -122.4194) if nothing is configured.

    Args:
        conditions: The ``conditions`` sub-dict from the VoxWatch config.
        _logger: Logger instance for debug/warning output.

    Returns:
        A ``(latitude, longitude)`` tuple of floats.
    """
    city_name = conditions.get("city", "").strip()
    if city_name:
        try:
            from astral.geocoder import database, lookup

            city_info = lookup(city_name, database())
            _logger.debug(
                "Resolved city '%s' to lat=%.4f lon=%.4f via astral geocoder.",
                city_name,
                city_info.latitude,
                city_info.longitude,
            )
            return float(city_info.latitude), float(city_info.longitude)
        except Exception as exc:
            _logger.warning(
                "Could not resolve city '%s' via astral geocoder (%s) — "
                "falling back to lat/lon.",
                city_name,
                exc,
            )

    lat = float(conditions.get("latitude", 37.7749))
    lon = float(conditions.get("longitude", -122.4194))
    return lat, lon


def is_between_sunset_and_sunrise(
    config: dict[str, Any],
    _logger: logging.Logger = logger,
    sunset_offset_minutes: int = 0,
    sunrise_offset_minutes: int = 0,
) -> bool:
    """Return True if the current UTC time is between today's sunset and tomorrow's sunrise.

    Uses the ``astral`` library to compute solar events at the configured
    location.  Location is resolved from ``conditions.city`` first; if that
    fails or is absent, ``conditions.latitude`` / ``conditions.longitude`` are
    used instead.

    Optional offset parameters shift the effective sunset/sunrise boundaries:
      - A negative ``sunset_offset_minutes`` means the window starts that many
        minutes *before* actual sunset (e.g. -30 = 30 min before sunset).
      - A positive ``sunrise_offset_minutes`` means the window ends that many
        minutes *after* actual sunrise (e.g. 30 = 30 min after sunrise).

    If ``astral`` is unavailable or the calculation fails, defaults to returning
    True (always active) so the service degrades gracefully rather than
    silently ignoring detections.

    Args:
        config: Full VoxWatch config dict.
        _logger: Logger instance for warnings/debug output.
        sunset_offset_minutes: Minutes to shift the sunset boundary.
            Negative values push the window start earlier.
        sunrise_offset_minutes: Minutes to shift the sunrise boundary.
            Positive values extend the window end later.

    Returns:
        True if the current time is in the nighttime window (post-sunset,
        pre-sunrise with offsets applied), or True if the calculation could
        not be completed.
    """
    try:
        from astral import LocationInfo
        from astral.sun import sun
    except ImportError:
        _logger.warning(
            "astral library not installed — defaulting to always active. "
            "Install with: pip install astral"
        )
        return True

    try:
        conditions = config.get("conditions", {})
        lat, lon = _resolve_location(conditions, _logger)

        location = LocationInfo(
            name="voxwatch",
            region="",
            timezone="UTC",
            latitude=lat,
            longitude=lon,
        )

        now_utc = datetime.now(tz=UTC)

        # Get today's and tomorrow's sun info so we can straddle midnight.
        sun_today = sun(location.observer, date=now_utc.date(), tzinfo=UTC)
        sun_tomorrow = sun(
            location.observer,
            date=(now_utc + timedelta(days=1)).date(),
            tzinfo=UTC,
        )

        # Apply offsets to the effective window boundaries.
        sunset_today = sun_today["sunset"] + timedelta(minutes=sunset_offset_minutes)
        sunrise_today = sun_today["sunrise"] + timedelta(minutes=sunrise_offset_minutes)
        sunrise_tomorrow = sun_tomorrow["sunrise"] + timedelta(
            minutes=sunrise_offset_minutes
        )

        # Nighttime window: sunset (today) <= now < sunrise (tomorrow).
        # The ``or`` handles the case where now < sunrise of today (pre-dawn).
        is_night = now_utc >= sunset_today or now_utc < sunrise_today

        _logger.debug(
            "Astral: now=%s sunset=%s (offset %+dm) sunrise=%s (offset %+dm) is_night=%s",
            now_utc.strftime("%H:%M:%S UTC"),
            sunset_today.strftime("%H:%M UTC"),
            sunset_offset_minutes,
            sunrise_tomorrow.strftime("%H:%M UTC"),
            sunrise_offset_minutes,
            is_night,
        )
        return is_night

    except Exception as exc:
        _logger.warning(
            "Sunset/sunrise calculation failed: %s — defaulting to active.", exc
        )
        return True


def is_in_fixed_window(
    start_str: str,
    end_str: str,
    _logger: logging.Logger = logger,
) -> bool:
    """Return True if the current local time falls within a fixed clock window.

    Handles midnight crossing — e.g. start=22:00, end=06:00 means the
    service is active from 10 PM through 6 AM the next day.

    If the time strings cannot be parsed, defaults to True (active) so that a
    misconfiguration never silently causes detections to be dropped.

    Args:
        start_str: Window start time as ``"HH:MM"`` (24-hour, local time).
        end_str: Window end time as ``"HH:MM"`` (24-hour, local time).
        _logger: Logger instance for parse-error warnings.

    Returns:
        True if the current local time is within the window.
    """
    try:
        now_time = datetime.now().time().replace(second=0, microsecond=0)
        start = dt_time(*[int(x) for x in start_str.split(":")])
        end = dt_time(*[int(x) for x in end_str.split(":")])
    except (ValueError, TypeError) as exc:
        _logger.warning(
            "Could not parse fixed hours '%s'–'%s': %s — defaulting to active.",
            start_str,
            end_str,
            exc,
        )
        return True

    if start <= end:
        # Simple same-day window (e.g. 08:00 – 20:00)
        return start <= now_time <= end
    else:
        # Midnight-crossing window (e.g. 22:00 – 06:00)
        # Active if now is AFTER start OR BEFORE end.
        return now_time >= start or now_time <= end


def check_cooldown(
    cooldowns: dict[str, float],
    camera_name: str,
    cooldown_seconds: float,
    _logger: logging.Logger = logger,
) -> bool:
    """Check the per-camera cooldown and mark it if the camera is not in cooldown.

    Prevents the same camera from firing the deterrent pipeline multiple times
    in quick succession (e.g. a person standing still who triggers repeated
    Frigate events).

    The cooldown timestamp is written the first time this function returns True
    for a camera.  Subsequent calls within ``cooldown_seconds`` will return False
    without updating the timestamp, so the cooldown window always runs from the
    *first* trigger.

    Mutates ``cooldowns`` in place when a trigger is allowed.

    Args:
        cooldowns: Mutable dict mapping camera_name -> ``time.monotonic()``
            timestamp of the last allowed trigger.  Pass the service's
            ``_cooldowns`` dict directly.
        camera_name: The Frigate/go2rtc name of the camera to check.
        cooldown_seconds: How long (in seconds) to suppress re-triggers after
            the first detection.
        _logger: Logger instance for debug output.

    Returns:
        True if the camera is NOT in cooldown (i.e., the event should proceed).
        False if the camera IS in cooldown (i.e., the event should be skipped).
    """
    now = time.monotonic()
    last_trigger = cooldowns.get(camera_name)

    if last_trigger is not None:
        elapsed = now - last_trigger
        if elapsed < cooldown_seconds:
            _logger.debug(
                "Cooldown active for %s (%.0fs remaining).",
                camera_name,
                cooldown_seconds - elapsed,
            )
            return False

    # Not in cooldown — mark the trigger timestamp and allow the event.
    cooldowns[camera_name] = now
    return True


def is_camera_active(
    config: dict[str, Any],
    camera_name: str,
    _logger: logging.Logger = logger,
) -> bool:
    """Check if a specific camera should be active right now.

    Priority: per-camera schedule > global active_hours.

    When the camera has a ``schedule`` block in its config, that schedule is
    evaluated and the result is returned without consulting the global
    ``conditions.active_hours`` setting.  When the camera has no ``schedule``
    (or the schedule field is None/absent), the function falls back to the
    global ``is_active_hours`` check so existing configs continue to work
    unchanged.

    Per-camera schedule modes:
      - ``"always"``:         Camera is always active (ignores global schedule).
      - ``"scheduled"``:      Active within the ``start``–``end`` time window.
      - ``"sunset_sunrise"``: Active from sunset (+ ``sunset_offset_minutes``)
                              to sunrise (+ ``sunrise_offset_minutes``).

    Unknown per-camera modes default to active so a misconfiguration never
    silently suppresses detections.

    Args:
        config: The full VoxWatch config dict.
        camera_name: Name of the camera to check (must match the key in
            ``config["cameras"]``).
        _logger: Logger instance for debug/warning output.

    Returns:
        True if the camera should respond to detections right now.
    """
    cameras = config.get("cameras", {})
    camera_cfg = cameras.get(camera_name, {})
    schedule = camera_cfg.get("schedule")

    # No per-camera schedule — fall back to the global active_hours check.
    if not schedule:
        return is_active_hours(config, _logger)

    mode = schedule.get("mode", "always")

    if mode == "always":
        return True

    if mode == "scheduled":
        return is_in_fixed_window(
            schedule.get("start", "22:00"),
            schedule.get("end", "06:00"),
            _logger,
        )

    if mode == "sunset_sunrise":
        return is_between_sunset_and_sunrise(
            config,
            _logger,
            sunset_offset_minutes=int(schedule.get("sunset_offset_minutes", 0)),
            sunrise_offset_minutes=int(schedule.get("sunrise_offset_minutes", 0)),
        )

    # Unknown per-camera mode — default to active so we don't silently miss events.
    _logger.warning(
        "Camera '%s': unknown per-camera schedule mode '%s' — defaulting to active.",
        camera_name,
        mode,
    )
    return True
