"""
Email alerts for security events.
Configure via environment variables (all optional — alerts are just logged if absent).
"""

import logging
import os
import smtplib
import threading
from datetime import datetime, timezone
from email.mime.text import MIMEText

log = logging.getLogger(__name__)


def _send(subject: str, body: str) -> None:
    admin_email = os.getenv("ADMIN_EMAIL", "")
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    from_addr = os.getenv("SMTP_FROM", admin_email)

    if not admin_email or not smtp_host:
        log.warning("ALERTE SÉCURITÉ (email non configuré) — %s", subject)
        return

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[Telex Sécurité] {subject}"
        msg["From"] = from_addr
        msg["To"] = admin_email
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.ehlo()
            s.starttls()
            if smtp_user:
                s.login(smtp_user, smtp_password)
            s.send_message(msg)
        log.info("Alerte email envoyée : %s", subject)
    except Exception as exc:
        log.error("Échec envoi email : %s", exc)


def _async(subject: str, body: str) -> None:
    threading.Thread(target=_send, args=(subject, body), daemon=True).start()


def client_locked(identifier: str, name: str, failure_count: int) -> None:
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    _async(
        f"Compte '{name}' verrouillé — activité suspecte",
        f"""Telex — Alerte de sécurité
═══════════════════════════════════

Le compte « {name} » (identifiant : {identifier}) a été VERROUILLÉ automatiquement.

Raison   : {failure_count} échecs d'authentification en 24h
Date/heure: {now}

ACTION REQUISE
──────────────
Connectez-vous à l'interface d'administration pour :
  • Lever le verrou si la tentative est légitime (famille qui a oublié le code)
  • Maintenir le verrou et signaler l'incident dans le cas contraire

Si vous ne reconnaissez pas cette activité, envisagez de changer
le mot de passe d'envoi du client.
""",
    )


def permanent_ban(ip: str, identifier: str, name: str) -> None:
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    _async(
        f"Bannissement permanent — {ip} → '{name}'",
        f"""Telex — Alerte de sécurité
═══════════════════════════════════

Une adresse IP a été bannie DÉFINITIVEMENT.

IP          : {ip}
Client cible: {name} ({identifier})
Date/heure  : {now}

Cette IP a atteint le niveau maximal de tentatives échouées (7 en 48h).

Vous pouvez lever ce ban depuis l'onglet Sécurité de l'interface admin
si l'adresse IP correspond à un membre de la famille (ex: nouveau réseau).
""",
    )
