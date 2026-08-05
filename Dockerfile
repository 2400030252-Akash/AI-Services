# =============================================================
#  AI Voice Calling Platform — Dockerfile
#  Multi-stage build: builder → production
#  Python 3.12, non-root user, minimal attack surface
# =============================================================

# ── Stage 1: dependency builder ──────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System dependencies required to compile native Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into an isolated prefix
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: production image ─────────────────────────────────
FROM python:3.12-slim AS production

# Copy compiled packages from builder
COPY --from=builder /install /usr/local

# Runtime system libs (libpq for asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --shell /bin/sh --no-create-home appuser

WORKDIR /app

# Copy application source
COPY --chown=appuser:appgroup app/ ./app/

USER appuser

EXPOSE 8000

# Gunicorn + Uvicorn workers for production throughput
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--log-level", "info"]
