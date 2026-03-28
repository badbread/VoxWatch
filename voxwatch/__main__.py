"""__main__.py — CLI entry point for the VoxWatch service.

Handles argument parsing, logging setup, config loading, signal registration,
and the asyncio event loop lifecycle.  The service logic itself lives in
:class:`~voxwatch.voxwatch_service.VoxWatchService`.

Usage (Docker / direct):
    python -m voxwatch
    python -m voxwatch --config /config/config.yaml
"""

import argparse
import asyncio
import logging
import logging.handlers
import os
import signal
import sys
import time

logger = logging.getLogger("voxwatch.service")


def _get_version() -> str:
    """Return the VoxWatch package version string.

    Returns:
        Version string from ``voxwatch.__version__``, or "unknown" on failure.
    """
    try:
        from voxwatch import __version__

        return __version__
    except ImportError:
        return "unknown"


def setup_logging(
    level_str: str,
    log_file: str | None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure root and voxwatch loggers with console and rotating file output.

    All voxwatch modules use ``logging.getLogger("voxwatch.*")`` so this
    single configuration covers the whole service.

    Rotation prevents unbounded disk growth — default is 10 MB per file
    with 5 backups (50 MB total max).  These values are configurable in
    config.yaml under ``logging.max_bytes`` and ``logging.backup_count``.

    Args:
        level_str: Log level string ("DEBUG", "INFO", "WARNING", "ERROR").
        log_file: Absolute path to a log file, or None for console-only output.
        max_bytes: Maximum size of each log file before rotation (default 10 MB).
        backup_count: Number of rotated backup files to keep (default 5).
    """
    level = getattr(logging, level_str.upper(), logging.INFO)

    # Consistent format used by all handlers — timestamp, logger name, level, message.
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear any pre-existing handlers to prevent duplicate log lines
    # (e.g. basicConfig auto-added a StreamHandler before we got here).
    root_logger.handlers.clear()

    # Console handler — always present so Docker logs work out of the box.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler — rotating to prevent unbounded disk growth.
    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            logger.info(
                "Logging to file: %s (max %d MB, %d backups)",
                log_file,
                max_bytes // (1024 * 1024),
                backup_count,
            )
        except OSError as exc:
            logger.warning(
                "Could not open log file %s: %s — logging to console only.",
                log_file,
                exc,
            )


def main() -> None:
    """Entry point for the VoxWatch service.

    Parses command-line arguments, configures logging, loads config, and
    runs the async event loop.  Registers SIGTERM/SIGINT handlers for
    graceful shutdown so Docker stop/restart works cleanly.

    Example:
        python -m voxwatch
        python -m voxwatch --config /config/config.yaml
    """
    from voxwatch.config import load_config_or_none
    from voxwatch.voxwatch_service import VoxWatchService

    parser = argparse.ArgumentParser(
        description="VoxWatch — AI-powered security audio deterrent system."
    )
    parser.add_argument(
        "--config",
        default="/config/config.yaml",
        help="Path to config.yaml (default: /config/config.yaml)",
    )
    args = parser.parse_args()

    # Bootstrap minimal logging before the config is loaded so any early
    # errors are visible rather than silently swallowed.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )

    # Attempt to load config — if it doesn't exist yet, wait for the setup
    # wizard to write it.  This lets the container start cleanly before
    # config.yaml has been created via the first-run web wizard.
    config = load_config_or_none(args.config)
    if config is None:
        logger.info(
            "config.yaml not found at %s — waiting for setup. "
            "Open the VoxWatch Dashboard at http://your-host:33344 to complete first-run setup.",
            args.config,
        )
        while config is None:
            time.sleep(5)
            config = load_config_or_none(args.config)
        logger.info("config.yaml detected — starting VoxWatch service.")

    # Re-configure logging with values from the loaded config.
    # Rotation settings prevent unbounded disk growth — configurable in config.yaml.
    log_cfg = config.get("logging", {})
    setup_logging(
        level_str=log_cfg.get("level", "INFO"),
        log_file=log_cfg.get("file"),
        max_bytes=log_cfg.get("max_bytes", 10 * 1024 * 1024),
        backup_count=log_cfg.get("backup_count", 5),
    )

    logger.info("Starting VoxWatch v%s", _get_version())
    logger.info("Config: %s", args.config)

    # Create the service instance.  Pass config_path so the hot-reload watcher
    # knows which file to monitor for changes.
    service = VoxWatchService(config, config_path=args.config)

    # Get (or create) the event loop before registering signal handlers,
    # because the handlers need a reference to the loop.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal(sig_name: str) -> None:
        """Schedule graceful shutdown on the event loop when a signal arrives.

        This function is called from the signal handler installed below.
        We schedule ``service.stop()`` as a coroutine on the loop because
        signal handlers must not block or call asyncio directly.

        Args:
            sig_name: Human-readable signal name for logging.
        """
        logger.info("Received %s — initiating graceful shutdown...", sig_name)
        # create_task is safe here because this runs on the event loop thread
        # (asyncio signal handlers are delivered on the loop thread).
        loop.create_task(service.stop())

    # Register POSIX signal handlers.  On Windows, only SIGINT (Ctrl-C) is
    # reliably supported; SIGTERM is a no-op on win32 but harmless to register.
    for sig, name in [(signal.SIGTERM, "SIGTERM"), (signal.SIGINT, "SIGINT")]:
        try:
            loop.add_signal_handler(sig, _handle_signal, name)
        except (NotImplementedError, AttributeError):
            # Windows does not support loop.add_signal_handler — fall back to
            # the standard signal module which handles SIGINT (Ctrl-C) only.
            signal.signal(sig, lambda s, f, n=name: _handle_signal(n))

    try:
        loop.run_until_complete(service.start())
    except KeyboardInterrupt:
        # Ctrl-C on platforms where the signal handler fallback isn't used.
        logger.info("KeyboardInterrupt received — shutting down...")
        loop.run_until_complete(service.stop())
    finally:
        # Cancel any remaining tasks and close the loop cleanly.
        pending = asyncio.all_tasks(loop)
        if pending:
            logger.debug("Cancelling %d pending task(s)...", len(pending))
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        logger.info("Event loop closed. Goodbye.")


if __name__ == "__main__":
    main()
