"""session.py — Shared aiohttp ClientSession for the ai_vision package.

A single module-level ``aiohttp.ClientSession`` is reused across all HTTP
calls (Frigate snapshot fetches, AI provider calls, presence checks) to avoid
the overhead of creating and tearing down a TCP connection pool on every
invocation.

The session is created lazily on first use via ``_get_session()``.  Callers
may also call ``await init_session()`` at service startup and
``await close_session()`` at graceful shutdown to manage the session lifecycle
explicitly.
"""

import logging

import aiohttp

logger = logging.getLogger("voxwatch.ai_vision")

# Module-level shared session.  None until first use or explicit init_session().
_session: aiohttp.ClientSession | None = None


async def init_session() -> None:
    """Create the module-level aiohttp session explicitly at service startup.

    Calling this is optional — ``_get_session()`` will create the session lazily
    if it has not been initialised.  Calling it at startup is preferred so that
    connection-pool creation happens at a predictable point rather than during
    the first live detection.

    Safe to call multiple times: a second call is a no-op if the session already
    exists and is open.
    """
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
        logger.debug("ai_vision: shared aiohttp session created")


async def close_session() -> None:
    """Close the module-level aiohttp session at service shutdown.

    Should be awaited during graceful shutdown to release the underlying TCP
    connection pool and avoid ``ResourceWarning`` noise in logs.  Safe to call
    even if the session was never created (no-op in that case).
    """
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        _session = None
        logger.debug("ai_vision: shared aiohttp session closed")


async def _get_session() -> aiohttp.ClientSession:
    """Return the shared aiohttp session, creating it lazily if necessary.

    This is the single point through which all HTTP calls in the ai_vision
    package obtain their session.  Functions call ``session = await
    _get_session()`` and use it directly (without a context-manager close).

    Returns:
        The module-level ``aiohttp.ClientSession``.  Guaranteed to be open.
    """
    global _session
    if _session is None or _session.closed:
        await init_session()
    # _session is always non-None after init_session(); satisfy the type checker.
    assert _session is not None
    return _session
