#!/usr/bin/env bash
# Push client code to the RPi and restart the service.
# Works whether the RPi is on your local network or in hotspot mode.
#
# Usage:
#   ./deploy/sync.sh                        # uses telex-arthur.local
#   ./deploy/sync.sh pi@192.168.4.1        # hotspot mode
#   ./deploy/sync.sh pi@telex-hugo.local   # different RPi

set -e

TARGET="${1:-pi@telex-arthur.local}"

echo "→ Syncing client/ to ${TARGET}:/opt/telex/client/"
rsync -av --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  client/ "${TARGET}:/opt/telex/client/"

echo "→ Restarting telex-client..."
ssh "${TARGET}" sudo systemctl restart telex-client

echo "→ Done. Logs:"
ssh "${TARGET}" sudo journalctl -u telex-client -n 20 --no-pager
