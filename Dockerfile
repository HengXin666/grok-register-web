# grok-register-web — full container with Chromium + Xvfb
# Supports protocol registration AND headful browser fallback (no host DISPLAY needed).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GROK_REGISTER_HOST=0.0.0.0 \
    GROK_REGISTER_PORT=5000 \
    GROK_REGISTER_BROWSER_HEADLESS=false \
    GROK_REGISTER_XVFB_DISPLAY=99 \
    GROK_REGISTER_XVFB_SCREEN=1365x900x24 \
    # Chromium flags friendly to containers
    CHROME_DEVEL_SANDBOX=/usr/lib/chromium/chrome-sandbox \
    LANG=C.UTF-8

WORKDIR /app

# Xvfb + Chromium + runtime libs for headful Chrome inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        wget \
        gnupg \
        xvfb \
        xauth \
        x11-utils \
        fonts-liberation \
        fonts-noto-color-emoji \
        chromium \
        chromium-driver \
        # Chromium shared libs (Debian meta often pulls these; keep explicit for slim)
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
        libx11-6 \
        libx11-xcb1 \
        libxcb1 \
        libxext6 \
        libxi6 \
        libxtst6 \
    && rm -rf /var/lib/apt/lists/* \
    && (command -v chromium >/dev/null || command -v chromium-browser >/dev/null) \
    && chromium --version || chromium-browser --version

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN chmod +x /app/scripts/docker-entrypoint.sh \
    && mkdir -p /app/data /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

# Chromium needs writable home for crash dumps / profiles.
ENV HOME=/home/appuser \
    GROK_REGISTER_BROWSER_PATH=/usr/bin/chromium \
    XDG_CONFIG_HOME=/home/appuser/.config \
    XDG_CACHE_HOME=/home/appuser/.cache

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${GROK_REGISTER_PORT:-5000}/" >/dev/null || exit 1

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
