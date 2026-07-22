#!/usr/bin/env bash
# Start Xvfb then the Turnstile solver HTTP API.
set -euo pipefail

DISPLAY_NUM="${SOLVER_XVFB_DISPLAY:-99}"
SCREEN="${SOLVER_XVFB_SCREEN:-1365x900x24}"
export DISPLAY=":${DISPLAY_NUM}"

HOST="${SOLVER_HOST:-0.0.0.0}"
PORT="${SOLVER_PORT:-5072}"
THREADS="${SOLVER_THREADS:-2}"
BROWSER_TYPE="${SOLVER_BROWSER_TYPE:-chromium}"

mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix 2>/dev/null || true
if [[ -e "/tmp/.X${DISPLAY_NUM}-lock" ]]; then
  rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}" 2>/dev/null || true
fi

echo "[solver-entrypoint] Xvfb DISPLAY=${DISPLAY} browser=${BROWSER_TYPE} threads=${THREADS}"
Xvfb "${DISPLAY}" -screen 0 "${SCREEN}" -nolisten tcp -ac +extension GLX +render -noreset &
XVFB_PID=$!

cleanup() {
  if kill -0 "${XVFB_PID}" 2>/dev/null; then
    kill "${XVFB_PID}" 2>/dev/null || true
    wait "${XVFB_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 50); do
  if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
if ! xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
  echo "[solver-entrypoint] ERROR: Xvfb failed on ${DISPLAY}" >&2
  exit 1
fi

cd /app/services/turnstile_solver
# headless=false under Xvfb is more reliable for Turnstile than pure headless.
exec python start.py \
  --browser_type "${BROWSER_TYPE}" \
  --thread "${THREADS}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --no-headless \
  ${SOLVER_EXTRA_ARGS:-}
