"""
config_editor.py — Config Editor API Router

Endpoints:
    GET  /api/config           — Return current config.yaml (secrets masked)
    PUT  /api/config           — Validate and save a new config
    POST /api/config/validate  — Dry-run validation only (no save)

The GET endpoint returns the full config structure with sensitive fields
replaced by '***MASKED***'. The PUT endpoint accepts the masked config and
restores the original secrets from disk before saving — so the browser never
needs to know the actual secret values.

All write operations go through Pydantic validation before touching the
filesystem. If validation fails the existing config.yaml is never modified.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from backend.models.config_models import ConfigValidationResult
from backend.services.config_service import config_service

logger = logging.getLogger("dashboard.router.config_editor")

router = APIRouter(prefix="/config", tags=["Configuration"])


@router.get(
    "",
    summary="Get current configuration",
    description=(
        "Returns the full VoxWatch config.yaml as a JSON object. "
        "Sensitive fields (api_key, mqtt_password) are masked with '***MASKED***'. "
        "Unresolved ${ENV_VAR} tokens are returned as-is."
    ),
)
async def get_config() -> Dict[str, Any]:
    """Return the current config.yaml with sensitive fields masked.

    Returns:
        JSON object matching the VoxWatchConfig schema, secrets masked.

    Raises:
        404: If config.yaml does not exist at the configured path.
        500: If the YAML cannot be parsed.
    """
    try:
        cfg = await config_service.get_config()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read config: {exc}",
        )
    return cfg


@router.get(
    "/raw",
    response_class=PlainTextResponse,
    summary="Get raw config.yaml text",
    description=(
        "Returns the raw YAML text of config.yaml for the advanced editor. "
        "Sensitive fields (API keys, passwords) are masked with '***MASKED***'."
    ),
)
async def get_config_raw() -> PlainTextResponse:
    """Return the config as masked YAML text for the advanced code editor.

    Reads the raw file, masks sensitive values, and returns as plain text
    so the CodeMirror editor can display it with YAML syntax highlighting.

    Returns:
        Plain text YAML with secrets masked.
    """
    import yaml

    try:
        cfg = await config_service.get_config()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read config: {exc}",
        )
    yaml_text = yaml.dump(cfg, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return PlainTextResponse(yaml_text, media_type="text/yaml")


@router.put(
    "",
    summary="Save configuration",
    description=(
        "Validates and atomically writes a new config.yaml. "
        "Masked field values ('***MASKED***') are preserved from the existing config — "
        "only non-masked fields are updated. "
        "Returns 422 if validation fails."
    ),
    status_code=status.HTTP_200_OK,
)
async def save_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and atomically write new config.yaml.

    The request body should be the full config JSON object (as returned by GET).
    Masked fields may be left as '***MASKED***' — the service restores the
    originals from disk.

    Args:
        data: Config dict from the request body.

    Returns:
        The saved config (re-read from disk, secrets masked).

    Raises:
        422: If the config fails Pydantic validation.
        500: If the file cannot be written.
    """
    # First validate to give a clear error before touching the filesystem
    validation = await config_service.validate_config(data)
    if not validation.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Configuration validation failed",
                "errors": validation.errors,
                "warnings": validation.warnings,
            },
        )

    try:
        await config_service.save_config(data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Configuration validation failed on save",
                "errors": [str(e) for e in exc.errors()],
            },
        )
    except OSError as exc:
        logger.error("Failed to write config.yaml: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write config file: {exc}",
        )

    # Return the saved config (re-read to confirm the write succeeded)
    saved = await config_service.get_config()
    return {
        "message": "Configuration saved successfully",
        "config": saved,
        "warnings": validation.warnings,
    }


@router.post(
    "/validate",
    summary="Validate configuration (dry run)",
    description=(
        "Validates a config object without saving it. "
        "Returns errors and warnings but does not modify config.yaml."
    ),
    response_model=ConfigValidationResult,
)
async def validate_config(data: Dict[str, Any]) -> ConfigValidationResult:
    """Dry-run config validation.

    Runs the submitted config through all Pydantic validators and returns
    a detailed error and warning list without writing to disk.

    Args:
        data: Config dict to validate.

    Returns:
        ConfigValidationResult with valid bool, errors list, warnings list.
    """
    return await config_service.validate_config(data)
