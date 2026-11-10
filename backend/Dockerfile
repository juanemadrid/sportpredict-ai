# =============================================================================
# SPORTPREDICT AI - BACKEND DOCKERFILE (FASTAPI + GUNICORN + UVICORN WORKERS)
# =============================================================================

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ENVIRONMENT=production \
    BACKEND_PORT=8000 \
    HOME=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    "pyjwt[crypto]>=2.9" \
    "alembic>=1.14" \
    "psycopg[binary]>=3.2" \
    "gunicorn>=23.0"

# Código de la aplicación y artefactos
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY artifacts ./artifacts
COPY data ./data

# Usuario no privilegiado por seguridad
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup --home /app appuser && \
    mkdir -p /app/data /app/artifacts/models /app/.cache && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Script de arranque: corre migraciones y arranca Gunicorn con workers Uvicorn
CMD ["sh", "-c", "python -m alembic upgrade head && gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:8000 --access-logfile - --error-logfile -"]
