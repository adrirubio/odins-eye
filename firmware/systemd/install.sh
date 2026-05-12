#!/usr/bin/env bash
# Install the Odin's Eye systemd units so the detector and dashboard start on boot.
# Run on the Pi with: sudo bash firmware/systemd/install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR=/etc/systemd/system

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo." >&2
    exit 1
fi

install -m 0644 "$SCRIPT_DIR/odins-eye-dashboard.service" "$SYSTEMD_DIR/odins-eye-dashboard.service"
install -m 0644 "$SCRIPT_DIR/odins-eye-detector.service" "$SYSTEMD_DIR/odins-eye-detector.service"

systemctl daemon-reload
systemctl enable odins-eye-dashboard.service odins-eye-detector.service
systemctl restart odins-eye-dashboard.service odins-eye-detector.service

echo
echo "Installed. Verify with:"
echo "  systemctl status odins-eye-dashboard.service"
echo "  systemctl status odins-eye-detector.service"
echo "  journalctl -u odins-eye-detector.service -f"
