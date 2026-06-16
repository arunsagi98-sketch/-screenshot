"""
Unified authentication dependency.

Accepts either:
  1. Bearer JWT token (role-based — preferred for frontend users)
  2. X-API-Key header (legacy / service-to-service)

If API_KEY is blank in .env, key-based auth is disabled.
If no JWT secret is set, JWT auth falls back to open (dev mode only).

Usage in any endpoint:
    from core.auth import require_api_key          # legacy
    from core.deps import require_admin            # JWT role guard (preferred)
"""
import logging

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security.api_key import APIKeyHeader

from core.config import get_settings
from core.security import decode_access_token

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    key: str = Security(_api_key_header),
) -> None:
    """
    Allow access if ANY of the following is true:
    1. A valid Bearer JWT token is present in Authorization header
    2. A valid X-API-Key header is present (when API_KEY is set)
    3. API_KEY is blank and APP_ENV is not production (dev open mode)
    """
    settings = get_settings()

    # ── 1. Try JWT Bearer token first ────────────────────────────────────────
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = decode_access_token(token)
        if payload:
            return  # valid JWT — allow through

    # ── 2. Try API key ────────────────────────────────────────────────────────
    if settings.api_key:
        if key == settings.api_key:
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing credentials. Use Bearer token or X-API-Key.",
        )

    # ── 3. Dev open mode (no API_KEY set, not production) ────────────────────
    if settings.app_env != "production":
        return

    # Production with no key configured — block
    logger.warning("Unauthenticated request blocked in production")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )
