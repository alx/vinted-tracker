# syntax=docker/dockerfile:1
# Image serves two roles from the same build:
#   poller   -> python poller.py   (default CMD)
#   dashboard-> python ui.py       (override CMD at `docker run`)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (better layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY poller.py ui.py index.html .

# Run as a dedicated non-root user; state is bind-mounted at /app/state.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/state \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 3110

# Per-role health checks are set at runtime (--health-cmd), since the poller
# exposes no HTTP endpoint and the dashboard does. See docs/DEPLOYMENT.md.
CMD ["python", "poller.py"]
