# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

# git is required for clone/branch/commit/push; build-essential for psycopg wheels fallback.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_ROOT=/data/workspaces

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root runtime user; owns the workspace volume.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/workspaces \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# Container-friendly default bot identity (override via env in production).
ENV GIT_AUTHOR_NAME=Coordinator3000 \
    GIT_AUTHOR_EMAIL=bot@coordinator3000.local

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
