FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for WeasyPrint
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libcairo2 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Production deps only (test tools live in requirements-dev.txt).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# .dockerignore keeps .env, local DBs, report HTML (candidate names), tests
# and node_modules out of the image.
COPY . .

# Run as an unprivileged user.
RUN useradd --system --uid 10001 --home-dir /app mindq \
    && mkdir -p /app/data \
    && chown -R mindq:mindq /app/data
USER mindq

EXPOSE 8000

# Each Uvicorn worker holds at most DB_POOL_SIZE + DB_MAX_OVERFLOW = 20 DB
# sockets (see app/database.py and DEPLOYMENT.md pool math). Raise
# WEB_CONCURRENCY only after re-checking the Supavisor client budget.
ENV WEB_CONCURRENCY=2
# Proxies whose X-Forwarded-* headers Uvicorn trusts (Nginx on the same host).
ENV FORWARDED_ALLOW_IPS=127.0.0.1
# Exec form via `sh -c ... exec`: env vars still expand, and uvicorn replaces
# the shell as PID 1 so SIGTERM reaches it. In-flight requests (submits) get
# 30s to finish before workers stop.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY} --timeout-graceful-shutdown 30 --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS}"]
