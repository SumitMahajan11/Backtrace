# Multi-stage hardened production Dockerfile for Backtrace Analysis Engine
# Stage 1: Dependency builder
FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Minimal unprivileged runtime image
FROM python:3.13-slim AS runner

WORKDIR /app

# Install git for repo analysis history extraction and curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root unprivileged service user (UID 10001)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -d /app -M appuser

# Prepare persistent data and logs directory
RUN mkdir -p /data /app/logs && \
    chown -R appuser:appgroup /data /app

# Copy application source code
COPY --chown=appuser:appgroup app /app/app
COPY --chown=appuser:appgroup docs /app/docs
COPY --chown=appuser:appgroup alembic /app/alembic
COPY --chown=appuser:appgroup alembic.ini /app/alembic.ini
COPY --chown=appuser:appgroup scripts /app/scripts

# Switch to unprivileged execution user
USER appuser

# Healthcheck definition
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

ENV ENVIRONMENT=production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]

