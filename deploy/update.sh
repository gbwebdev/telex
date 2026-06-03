#!/usr/bin/env bash
# Telex auto-update — vérifie la dernière release GitHub et met à jour si besoin.
# Lancé par telex-update.timer au démarrage et toutes les 24h.
set -euo pipefail

INSTALL_DIR="/opt/telex"
CLIENT_DIR="$INSTALL_DIR/client"
VENV="$INSTALL_DIR/venv"
SERVICE_DIR="/etc/systemd/system"
VERSION_FILE="$INSTALL_DIR/VERSION"
REPO="gbwebdev/telex"

log() { echo "[telex-update] $*"; }

# ── Version installée ─────────────────────────────────────────────────────────
CURRENT=$(cat "$VERSION_FILE" 2>/dev/null || echo "")
if [[ "$CURRENT" == "dev" ]]; then
    log "Mode développement — mise à jour automatique désactivée."
    exit 0
fi

# ── Dernière release GitHub ───────────────────────────────────────────────────
LATEST=$(curl -fsSL --max-time 10 \
    "https://api.github.com/repos/${REPO}/releases/latest" \
    2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])" \
    2>/dev/null || echo "")

if [[ -z "$LATEST" ]]; then
    log "Aucune release disponible ou pas de connexion — rien à faire."
    exit 0
fi

if [[ "$CURRENT" == "$LATEST" ]]; then
    log "Déjà à jour ($CURRENT)."
    exit 0
fi

log "Mise à jour : $CURRENT → $LATEST"

# ── Téléchargement ────────────────────────────────────────────────────────────
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

curl -fsSL --max-time 120 \
    "https://github.com/${REPO}/archive/refs/tags/${LATEST}.tar.gz" \
    | tar -xz -C "$TMP_DIR"

# Le dossier extrait s'appelle telex-X.Y.Z (sans le "v" du tag)
SRC="$TMP_DIR/telex-${LATEST#v}"
[[ -d "$SRC" ]] || SRC="$TMP_DIR/telex-${LATEST}"

if [[ ! -d "$SRC/client" ]]; then
    log "Archive inattendue — abandon."
    exit 1
fi

# ── Installation ──────────────────────────────────────────────────────────────
# Arrêt des services avant remplacement du code
systemctl stop telex-client telex-portal 2>/dev/null || true

cp -r "$SRC/client/." "$CLIENT_DIR/"
"$VENV/bin/pip" install -r "$CLIENT_DIR/requirements.txt" --quiet

# Mise à jour des fichiers de service si modifiés
for svc in telex-client.service telex-portal.service telex-wifi.service \
           telex-update.service telex-update.timer; do
    [[ -f "$SRC/deploy/$svc" ]] && cp "$SRC/deploy/$svc" "$SERVICE_DIR/$svc"
done

# Mise à jour du script update lui-même
[[ -f "$SRC/deploy/update.sh" ]] && cp "$SRC/deploy/update.sh" "$INSTALL_DIR/update.sh"

echo "$LATEST" > "$VERSION_FILE"

systemctl daemon-reload
systemctl start telex-client telex-portal 2>/dev/null || true

log "Mise à jour terminée → $LATEST"
