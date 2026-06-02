#!/usr/bin/env bash
# Telex client installer — Raspberry Pi Zero W / Raspberry Pi OS Bookworm
# Usage: sudo bash install.sh
#
# Designed for headless use: run via SSH after flashing with Raspberry Pi Imager.
# The server URL, identifier and password are configured afterwards via the
# web portal at http://<ip-du-rpi>.

set -euo pipefail

INSTALL_DIR="/opt/telex"
CLIENT_DIR="$INSTALL_DIR/client"
VENV="$INSTALL_DIR/venv"
SERVICE_DIR="/etc/systemd/system"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Root check ────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo "Error: run with sudo." >&2
  exit 1
fi

echo ""
echo "╔══════════════════════════════╗"
echo "║   TELEX — Installation RPi   ║"
echo "╚══════════════════════════════╝"
echo ""

# ── System packages ───────────────────────────────────────────────────────────
echo "[1/6] Mise à jour des paquets système…"
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    libusb-1.0-0 \
    network-manager \
    avahi-daemon \
    git \
    2>/dev/null

# Ensure NetworkManager manages WiFi (important on Bookworm)
systemctl enable NetworkManager --quiet 2>/dev/null || true
systemctl start  NetworkManager --quiet 2>/dev/null || true

# ── Copy client code ──────────────────────────────────────────────────────────
echo "[2/6] Installation du code client…"
mkdir -p "$CLIENT_DIR"
cp -r "$REPO_DIR/client/." "$CLIENT_DIR/"

# ── Python virtualenv ─────────────────────────────────────────────────────────
echo "[3/6] Création de l'environnement Python…"
if [[ ! -d "$VENV" ]]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -r "$CLIENT_DIR/requirements.txt" --quiet

# ── USB printer permissions ───────────────────────────────────────────────────
echo "[4/6] Permissions USB imprimante…"
cat > /etc/udev/rules.d/99-telex-printer.rules << 'EOF'
# Telex: allow access to USB thermal printers without root
SUBSYSTEM=="usb", ATTRS{bDeviceClass}=="07", MODE="0666"
SUBSYSTEM=="usb", ATTRS{bInterfaceClass}=="07", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", MODE="0666"
EOF
udevadm control --reload-rules 2>/dev/null || true

# ── Config ────────────────────────────────────────────────────────────────────
echo "[5/6] Configuration initiale…"
mkdir -p /etc/telex

if [[ ! -f /etc/telex/config.json ]]; then
    cat > /etc/telex/config.json << 'EOF'
{
  "server_url": "",
  "identifier": "",
  "password": "",
  "poll_interval": 60,
  "gpio_ticket_pin": 17
}
EOF
    echo "       → Config créée (à remplir via le portail web)"
else
    echo "       → Config existante conservée"
fi

# ── Systemd services ──────────────────────────────────────────────────────────
echo "[6/6] Services systemd…"

cp "$SCRIPT_DIR/telex-wifi.service"   "$SERVICE_DIR/"
cp "$SCRIPT_DIR/telex-portal.service" "$SERVICE_DIR/"
cp "$SCRIPT_DIR/telex-client.service" "$SERVICE_DIR/"

systemctl daemon-reload

systemctl enable telex-portal.service --quiet
systemctl enable telex-wifi.service   --quiet
systemctl enable telex-client.service --quiet

# Restart portal if already running (for re-installs)
if systemctl is-active --quiet telex-portal; then
    systemctl restart telex-portal
fi

# ── Summary ───────────────────────────────────────────────────────────────────
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
HOSTNAME=$(hostname)

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║            Installation terminée ✓                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Les services démarreront automatiquement au prochain boot."
echo "  Pour démarrer maintenant sans redémarrer :"
echo ""
echo "    sudo systemctl start telex-portal"
echo "    sudo systemctl start telex-wifi"
echo "    sudo systemctl start telex-client"
echo ""
echo "  ┌─────────────────────────────────────────────────────┐"
echo "  │  Portail de configuration :                         │"
if [[ -n "$IP" ]]; then
echo "  │    http://$IP"
fi
echo "  │    http://$HOSTNAME.local"
echo "  │                                                     │"
echo "  │  Ouvrez cette adresse dans votre navigateur         │"
echo "  │  (même réseau WiFi) pour configurer le client.      │"
echo "  └─────────────────────────────────────────────────────┘"
echo ""
echo "  Rappel : créez d'abord le client dans l'interface"
echo "  admin de votre serveur Telex, puis saisissez"
echo "  l'identifiant et le mot de passe dans le portail."
echo ""
