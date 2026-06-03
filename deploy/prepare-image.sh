#!/usr/bin/env bash
# Telex — Préparation du Pi avant capture de l'image distribuable.
# À exécuter sur le Pi avec sudo, juste avant d'éteindre pour retirer la SD.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Exécuter avec sudo." >&2
    exit 1
fi

echo ""
echo "╔──────────────────────────────────────────────────╗"
echo "║   TELEX — Préparation de l'image distribuable    ║"
echo "╚──────────────────────────────────────────────────╝"
echo ""
echo "Ce script prépare la carte SD pour être clonée et distribuée."
echo "Il efface les données sensibles et optimise la compression."
echo ""
read -rp "Continuer ? [o/N] " CONFIRM
[[ "${CONFIRM,,}" != "o" ]] && exit 0
echo ""

# ── Config Telex : remise à zéro ─────────────────────────────────────────────
cat > /etc/telex/config.json << 'EOF'
{
  "server_url": "",
  "identifier": "",
  "password": "",
  "poll_interval": 60,
  "gpio_ticket_pin": 17
}
EOF
rm -f /etc/telex/state.json
echo "✓ Config Telex réinitialisée"

# ── Données sensibles ─────────────────────────────────────────────────────────
rm -f /home/pi/.bash_history /root/.bash_history 2>/dev/null || true
truncate -s 0 /home/pi/.bash_history /root/.bash_history 2>/dev/null || true
echo "✓ Historique bash effacé"

# Clés SSH régénérées automatiquement au premier boot du clone
rm -f /etc/ssh/ssh_host_*
echo "✓ Clés SSH hôte supprimées (régénérées au premier boot)"

# ── Cache et logs ─────────────────────────────────────────────────────────────
apt-get clean -qq
rm -rf /var/cache/apt/archives/ /var/lib/apt/lists/*
echo "✓ Cache APT nettoyé"

journalctl --vacuum-time=1s 2>/dev/null || true
find /var/log -type f \( -name "*.log" -o -name "*.gz" -o -name "*.1" \) \
    -delete 2>/dev/null || true
find /var/log -type f -exec truncate -s 0 {} \; 2>/dev/null || true
echo "✓ Logs effacés"

rm -rf /tmp/* /var/tmp/* 2>/dev/null || true
echo "✓ /tmp nettoyé"

# ── Zero-fill de l'espace libre (améliore dramatiquement la compression) ──────
echo "→ Remplissage de l'espace libre avec des zéros…"
echo "  (peut prendre quelques minutes)"
dd if=/dev/zero of=/fillfile bs=1M 2>/dev/null || true
rm -f /fillfile
sync
echo "✓ Espace libre zéro-rempli"

# ── Résumé ────────────────────────────────────────────────────────────────────
echo ""
echo "╔──────────────────────────────────────────────────╗"
echo "║  Prêt pour la capture d'image.                   ║"
echo "║                                                  ║"
echo "║  Éteignez le Pi maintenant :                     ║"
echo "║    sudo shutdown -h now                          ║"
echo "║                                                  ║"
echo "║  Ensuite, sur votre Mac :                        ║"
echo "║    bash deploy/create-image.sh                   ║"
echo "╚──────────────────────────────────────────────────╝"
echo ""
