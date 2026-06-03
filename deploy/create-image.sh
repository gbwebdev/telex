#!/usr/bin/env bash
# Telex — Création de l'image distribuable depuis la carte SD.
# À exécuter sur macOS après avoir éteint le Pi et retiré la carte SD.
set -euo pipefail

echo ""
echo "╔──────────────────────────────────────────────────╗"
echo "║   TELEX — Création de l'image distribuable       ║"
echo "╚──────────────────────────────────────────────────╝"
echo ""

# ── Lister les disques pour identifier la carte SD ───────────────────────────
echo "Disques disponibles :"
echo "────────────────────"
diskutil list external physical 2>/dev/null || diskutil list
echo ""

read -rp "Numéro du disque SD (ex: 2 pour /dev/disk2) : " DISK_NUM
DEVICE="/dev/disk${DISK_NUM}"
RAW_DEVICE="/dev/rdisk${DISK_NUM}"

# ── Confirmation ──────────────────────────────────────────────────────────────
echo ""
echo "Informations sur /dev/disk${DISK_NUM} :"
diskutil info "$DEVICE" | grep -E "Device Node|Media Name|Total Size|Removable" || true
echo ""
read -rp "Confirmer la capture de ce disque ? [o/N] " CONFIRM
[[ "${CONFIRM,,}" != "o" ]] && { echo "Annulé."; exit 0; }

# ── Nom du fichier de sortie ──────────────────────────────────────────────────
DATE=$(date +%Y%m%d)
OUTFILE="telex-${DATE}.img.gz"

if [[ -f "$OUTFILE" ]]; then
    read -rp "$OUTFILE existe déjà. Écraser ? [o/N] " OW
    [[ "${OW,,}" != "o" ]] && exit 0
fi

# ── Démontage des partitions ──────────────────────────────────────────────────
echo ""
echo "→ Démontage des partitions…"
diskutil unmountDisk "$DEVICE" || true

# ── Capture + compression en une passe ───────────────────────────────────────
echo "→ Lecture de la carte SD et compression…"
echo "  (cette opération peut prendre 10-20 minutes selon la taille de la carte)"
echo ""

START=$(date +%s)
sudo dd if="$RAW_DEVICE" bs=4m 2>/tmp/telex-dd-err | gzip > "$OUTFILE"
END=$(date +%s)

# ── Résumé ────────────────────────────────────────────────────────────────────
SIZE=$(du -sh "$OUTFILE" | cut -f1)
ELAPSED=$(( END - START ))
MINUTES=$(( ELAPSED / 60 ))
SECONDS=$(( ELAPSED % 60 ))

echo ""
echo "╔──────────────────────────────────────────────────╗"
echo "║  Image créée avec succès !                       ║"
printf "║  Fichier  : %-37s║\n" "$OUTFILE"
printf "║  Taille   : %-37s║\n" "$SIZE (compressé)"
printf "║  Durée    : %-37s║\n" "${MINUTES}m${SECONDS}s"
echo "║                                                  ║"
echo "║  Pour flasher : Raspberry Pi Imager              ║"
echo "║  → «Use custom» → sélectionner ce fichier .gz    ║"
echo "╚──────────────────────────────────────────────────╝"
echo ""
