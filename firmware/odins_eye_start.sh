#!/usr/bin/env bash
# Manual launcher for roadside testing — runs detector + dashboard together
# in the foreground. Use this when you want the gyro calibration prompt and
# live burst logs in your terminal. For autostart on boot, use the systemd
# units in firmware/systemd/ instead.

set -u

REPO_FIRMWARE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DETECTOR="$REPO_FIRMWARE_DIR/odins_eye_speed_monitor.py"
DASHBOARD="$REPO_FIRMWARE_DIR/odins_eye_dashboard_server.py"
CAPTURES_DIR="$HOME/odins-eye-captures"
DASHBOARD_PORT=8080
DASHBOARD_LOG="$HOME/dashboard.log"

DASHBOARD_PID=""

cleanup() {
    if [[ -n "$DASHBOARD_PID" ]] && kill -0 "$DASHBOARD_PID" 2>/dev/null; then
        echo ""
        echo "[launcher] stopping dashboard (pid $DASHBOARD_PID)"
        kill "$DASHBOARD_PID" 2>/dev/null
        wait "$DASHBOARD_PID" 2>/dev/null
    fi
}
trap cleanup EXIT INT TERM

echo "[launcher] starting dashboard on port $DASHBOARD_PORT"
python3 "$DASHBOARD" \
    --captures-dir "$CAPTURES_DIR" \
    --port "$DASHBOARD_PORT" \
    >"$DASHBOARD_LOG" 2>&1 &
DASHBOARD_PID=$!

sleep 1
if ! kill -0 "$DASHBOARD_PID" 2>/dev/null; then
    echo "[launcher] dashboard failed to start, see $DASHBOARD_LOG" >&2
    exit 1
fi

PI_IP=$(hostname -I | awk '{print $1}')
echo "[launcher] dashboard live at http://${PI_IP}:${DASHBOARD_PORT}  (log: $DASHBOARD_LOG)"
echo "[launcher] starting detector — Ctrl-C stops both"
echo ""

python3 "$DETECTOR" "$@"
