# grok-register-web — protocol registration console
# Protocol path needs no Chrome; browser fallback requires a host with DISPLAY/Xvfb.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GROK_REGISTER_HOST=0.0.0.0 \
    GROK_REGISTER_PORT=5000

WORKDIR /app

# Minimal runtime libs for curl_cffi / openssl; no full Chrome (use host Xvfb or external solver).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libglib2.0-0 \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libpango-1.0-0 \
        libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/data \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${GROK_REGISTER_PORT:-5000}/" >/dev/null || exit 1

# --allow-remote is required when binding 0.0.0.0 (see app.py)
CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "5000", "--allow-remote"]
