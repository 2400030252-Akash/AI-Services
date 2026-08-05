"""
FastAPI application entry point.

Routers are imported and registered here as each module is built.
Do NOT add business logic to this file.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings

# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered voice calling platform — admin API.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,   # CORS_ALLOWED_ORIGINS in .env
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# System routes
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    tags=["system"],
    summary="Health check",
    response_description="Returns service liveness status.",
)
async def health_check() -> dict:
    return {"status": "ok", "version": settings.app_version}


# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------
from app.api.auth import router as auth_router            # noqa: E402
from app.api.calls import router as calls_router          # noqa: E402
from app.api.dashboard import router as dashboard_router  # noqa: E402
from app.api.voice import router as voice_router          # noqa: E402

app.include_router(auth_router,      prefix="/api/v1/auth",      tags=["auth"])
app.include_router(calls_router,     prefix="/api/v1/calls",     tags=["calls"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(voice_router,     prefix="/api/v1/voice",     tags=["voice"])

