#!/usr/bin/env bash
# Container entrypoint: always provide a virtual DISPLAY so headful Chrome works.
set -euo pipefail

HOST="${GROK_REGISTER_HOST:-0.0.0.0}"
PORT="${GROK_REGISTER_PORT:-5000}"
DISPLAY_NUM="${GROK_REGISTER_XVFB_DISPLAY:-99}"
SCREEN="${GROK_REGISTER_XVFB_SCREEN:-1365x900x24}"
export DISPLAY=":${DISPLAY_NUM}"

# Prefer Chromium/Chrome shipped in the image.
if [[ -z "${GROK_REGISTER_BROWSER_PATH:-}" ]]; then
  for candidate in \
    /usr/bin/chromium \
    /usr/bin/chromium-browser \
    /usr/bin/google-chrome-stable \
    /usr/bin/google-chrome
  do
    if [[ -x "${candidate}" ]]; then
      export GROK_REGISTER_BROWSER_PATH="${candidate}"
      break
    fi
  done
fi

# Headful inside Xvfb (matches scripts/run_with_xvfb.sh intent).
export GROK_REGISTER_BROWSER_HEADLESS="${GROK_REGISTER_BROWSER_HEADLESS:-false}"

# Chrome in Docker often needs larger /dev/shm; compose sets shm_size.
mkdir -p /tmp/.X11-unix /app/data
chmod 1777 /tmp/.X11-unix 2>/dev/null || true

# Kill stale Xvfb on the same display (container restart).
if [[ -e "/tmp/.X${DISPLAY_NUM}-lock" ]]; then
  rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}" 2>/dev/null || true
fi

echo "[entrypoint] starting Xvfb on DISPLAY=${DISPLAY} screen=${SCREEN}"
Xvfb "${DISPLAY}" -screen 0 "${SCREEN}" -nolisten tcp -ac +extension GLX +render -noreset &
XVFB_PID=$!

cleanup() {
  if kill -0 "${XVFB_PID}" 2>/dev/null; then
    kill "${XVFB_PID}" 2>/dev/null || true
    wait "${XVFB_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Wait until X is accepting connections.
for _ in $(seq 1 50); do
  if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
if ! xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
  echo "[entrypoint] ERROR: Xvfb failed to start on ${DISPLAY}" >&2
  exit 1
fi

echo "[entrypoint] browser=${GROK_REGISTER_BROWSER_PATH:-auto} headless=${GROK_REGISTER_BROWSER_HEADLESS}"
echo "[entrypoint] starting app on ${HOST}:${PORT}"

# Allow extra args, default to production bind.
if [[ "$#" -gt 0 ]]; then
  exec python app.py "$@"
fi
exec python app.py --host "${HOST}" --port "${PORT}" --allow-remote
