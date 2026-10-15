"""
app/api/deps_voice_agent.py
===========================
Authentication dependency for the Exotel Voice Agent Custom API integration.

Validates that incoming HTTP requests carry the configured secret key.
Supports:
  1. Header: X-API-Key: <secret>
  2. Header: Authorization: Bearer <secret>
  3. Query Param: ?api_key=<secret>

Security:
- OpenAPI security schemes (APIKeyHeader & HTTPBearer) registered so Swagger UI
  and client SDKs recognize authentication requirements and send credentials.
- Constant-time string comparison (secrets.compare_digest) to prevent timing attacks.
- Safe logging — credentials are never written to log files.
- Rejects unauthorized requests with HTTP 401.
"""
from __future__ import annotations

import logging
import secrets
from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

logger = logging.getLogger(__name__)

# OpenAPI security scheme definitions for Swagger UI
api_key_header_scheme = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Exotel Voice Agent secret key passed via X-API-Key header",
)
http_bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Exotel Voice Agent secret key passed via Authorization: Bearer <token> header",
)


async def validate_voice_agent_auth(
    request: Request,
    api_key_header: str | None = Security(api_key_header_scheme),
    bearer_credentials: HTTPAuthorizationCredentials | None = Security(http_bearer_scheme),
) -> None:
    """
    FastAPI dependency guard for the Exotel Voice Agent endpoint.

    Extracts and validates the authentication key from:
      1. X-API-Key header (OpenAPI APIKeyHeader)
      2. Authorization: Bearer <token> header (OpenAPI HTTPBearer)
      3. Fallback request headers / query params

    Raises HTTP 401 Unauthorized if the key is missing or invalid.
    """
    configured_key = settings.voice_agent_api_key

    # Dev bypass: allow if no key is configured in debug mode
    if settings.debug and not configured_key:
        logger.warning(
            "Voice Agent authentication BYPASSED — VOICE_AGENT_API_KEY is not configured in debug mode. "
            "Configure VOICE_AGENT_API_KEY in backend/.env for production security!"
        )
        return

    if not configured_key:
        logger.error(
            "VOICE_AGENT_API_KEY is not configured on server. Rejecting external voice agent request."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Voice agent integration is not configured with an API key on the server.",
        )

    # Collect provided candidate keys from supported channels
    candidates: list[str] = []

    # 1. From APIKeyHeader (X-API-Key)
    if api_key_header and api_key_header.strip():
        candidates.append(api_key_header.strip())

    # 2. From HTTPBearer (Authorization: Bearer <token>)
    if bearer_credentials and bearer_credentials.credentials:
        token = bearer_credentials.credentials.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if token and token not in candidates:
            candidates.append(token)

    # 3. Direct inspection of headers (supports "Authorization: Bearer", "Basic", "apikey", or bare header)
    raw_x_key = request.headers.get("X-API-Key")
    if raw_x_key and raw_x_key.strip():
        cleaned = raw_x_key.strip()
        if cleaned not in candidates:
            candidates.append(cleaned)

    raw_auth = request.headers.get("Authorization", "").strip()
    if raw_auth:
        if raw_auth.lower().startswith("bearer "):
            val = raw_auth[7:].strip()
            if val and val not in candidates:
                candidates.append(val)
        elif raw_auth.lower().startswith("apikey "):
            val = raw_auth[7:].strip()
            if val and val not in candidates:
                candidates.append(val)
        elif raw_auth.lower().startswith("basic "):
            import base64
            try:
                decoded = base64.b64decode(raw_auth[6:].strip()).decode("utf-8", "ignore")
                if ":" in decoded:
                    u, p = decoded.split(":", 1)
                    if u.strip() and u.strip() not in candidates:
                        candidates.append(u.strip())
                    if p.strip() and p.strip() not in candidates:
                        candidates.append(p.strip())
                else:
                    if decoded.strip() and decoded.strip() not in candidates:
                        candidates.append(decoded.strip())
            except Exception:
                pass
        else:
            if raw_auth not in candidates:
                candidates.append(raw_auth)

    # 4. Fallback: query parameters (?api_key=<secret>, ?token=<secret>, ?key=<secret>)
    for q_param in ("api_key", "token", "key"):
        query_val = request.query_params.get(q_param)
        if query_val and query_val.strip():
            cleaned_query = query_val.strip()
            if cleaned_query not in candidates:
                candidates.append(cleaned_query)

    # 5. Fallback: path parameters (/ask/{auth_token}, /{auth_token}/ask)
    for p_param in ("auth_token", "token", "api_key"):
        path_val = request.path_params.get(p_param)
        if path_val and path_val.strip():
            cleaned_path = path_val.strip()
            if cleaned_path not in candidates:
                candidates.append(cleaned_path)

    # 6. Fallback: JSON body inspection (for platforms that allow body parameters with defaults)
    try:
        body_bytes = await request.body()
        if body_bytes:
            import json
            body_data = json.loads(body_bytes)
            if isinstance(body_data, dict):
                body_token = (
                    body_data.get("api_key")
                    or body_data.get("token")
                    or (body_data.get("parameters") or {}).get("api_key")
                )
                if body_token and isinstance(body_token, str) and body_token.strip():
                    cleaned_body = body_token.strip()
                    if cleaned_body not in candidates:
                        candidates.append(cleaned_body)
    except Exception:
        pass

    # If no credentials were provided at all
    if not candidates:
        logger.warning(
            "Voice Agent request rejected: missing authentication credentials "
            "(no X-API-Key, Authorization header, query parameter, or path token from IP: %s)",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing API key. Provide key in X-API-Key, Authorization header, URL query (?api_key=...), or path (/ask/{token}).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Constant-time comparison against configured key
    is_valid = any(secrets.compare_digest(candidate, configured_key) for candidate in candidates)

    if not is_valid:
        logger.warning(
            "Voice Agent request rejected: invalid API key from IP: %s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Successful authentication
    logger.debug("Voice Agent request authenticated successfully")

