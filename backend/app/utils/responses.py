"""
Shared response helpers.

Provides a uniform error response factory matching the API contract:
    { "error": true, "message": "...", "code": "SNAKE_CASE" }
"""
from fastapi import HTTPException
from fastapi.responses import JSONResponse


def error_response(
    message: str,
    code: str,
    status_code: int = 400,
) -> JSONResponse:
    """Return a JSON error response in the standard platform format."""
    return JSONResponse(
        status_code=status_code,
        content={"error": True, "message": message, "code": code},
    )


def raise_http_error(message: str, code: str, status_code: int = 400) -> None:
    """Raise an HTTPException whose detail conforms to the platform error format."""
    raise HTTPException(
        status_code=status_code,
        detail={"error": True, "message": message, "code": code},
    )
