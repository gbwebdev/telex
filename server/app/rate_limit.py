"""
DB-backed rate limiter — persistent across server restarts.

Per (IP × identifier) escalation:
  Level 1 : ≥3 failures in 15 min  → blocked  1 hour
  Level 2 : ≥5 failures in  1 hour → blocked 72 hours
  Level 3 : ≥7 failures in 48 hours → blocked permanently + admin email

Per client (all IPs combined):
  ≥10 failures in 24 hours → client send-page locked + admin email
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, text
from sqlmodel import Session, select

from . import email_alert
from .models import Client, FailedAttempt, IPBan

# ── Thresholds ────────────────────────────────────────────────────────────────

LEVELS = {
    1: {"window": timedelta(minutes=15), "threshold": 3, "duration": timedelta(hours=1)},
    2: {"window": timedelta(hours=1),    "threshold": 5, "duration": timedelta(hours=72)},
    3: {"window": timedelta(hours=48),   "threshold": 7, "duration": None},  # permanent
}
LEVEL_LABELS = {1: "1 heure", 2: "72 heures", 3: "définitivement"}

CLIENT_WINDOW = timedelta(hours=24)
CLIENT_THRESHOLD = 10


class RateLimitExceeded(Exception):
    def __init__(self, message: str):
        self.message = message


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(seconds: int) -> str:
    if seconds < 120:
        return f"{seconds} secondes"
    if seconds < 7200:
        return f"{seconds // 60} minutes"
    return f"{seconds // 3600} heure(s)"


def _count_ip(ip: str, identifier: str, since: datetime, session: Session) -> int:
    return session.exec(
        select(func.count(FailedAttempt.id)).where(
            FailedAttempt.ip == ip,
            FailedAttempt.identifier == identifier,
            FailedAttempt.attempted_at >= since,
        )
    ).one()


def _count_global(identifier: str, since: datetime, session: Session) -> int:
    return session.exec(
        select(func.count(FailedAttempt.id)).where(
            FailedAttempt.identifier == identifier,
            FailedAttempt.attempted_at >= since,
        )
    ).one()


def _active_ban(ip: str, identifier: str, session: Session) -> Optional[IPBan]:
    return session.exec(
        select(IPBan)
        .where(IPBan.ip == ip, IPBan.identifier == identifier, IPBan.active == True)
        .order_by(IPBan.level.desc())
    ).first()


# ── Public API ────────────────────────────────────────────────────────────────

def check_allowed(ip: str, identifier: str, session: Session) -> None:
    """
    Call BEFORE checking the password.
    Raises RateLimitExceeded if the request must be rejected.
    """
    now = datetime.utcnow()

    # Client-level lock
    client = session.get(Client, identifier)
    if client and client.send_locked:
        raise RateLimitExceeded(
            "Ce service est temporairement indisponible. "
            "Contactez l'administrateur."
        )

    # IP-level ban
    ban = _active_ban(ip, identifier, session)
    if ban:
        if ban.banned_until is None:
            raise RateLimitExceeded("Accès définitivement bloqué pour cette adresse.")
        if now < ban.banned_until:
            remaining = int((ban.banned_until - now).total_seconds())
            raise RateLimitExceeded(
                f"Trop de tentatives. Accès bloqué pour encore {_fmt(remaining)}."
            )
        # Expired — deactivate lazily
        ban.active = False
        session.add(ban)
        session.commit()


def record_failure(ip: str, identifier: str, session: Session) -> int:
    """
    Call AFTER a failed password check.
    Logs the attempt, escalates ban level if needed, locks client if threshold crossed.
    Returns remaining attempts before level-1 kicks in (for UI feedback).
    """
    now = datetime.utcnow()

    session.add(FailedAttempt(ip=ip, identifier=identifier, attempted_at=now))
    session.flush()  # ensure this attempt is visible in subsequent counts

    # Determine highest triggered ban level
    triggered_level = 0
    for level in (3, 2, 1):
        cfg = LEVELS[level]
        count = _count_ip(ip, identifier, now - cfg["window"], session)
        if count >= cfg["threshold"]:
            triggered_level = level
            break

    permanent_ban_triggered = False
    if triggered_level:
        permanent_ban_triggered = _upsert_ban(ip, identifier, triggered_level, session, now)

    # Global per-client counter (all IPs)
    client_failures = _count_global(identifier, now - CLIENT_WINDOW, session)
    if client_failures >= CLIENT_THRESHOLD:
        _lock_client(identifier, client_failures, session, now)

    session.commit()

    if permanent_ban_triggered:
        client = session.get(Client, identifier)
        email_alert.permanent_ban(ip, identifier, client.name if client else identifier)

    # Remaining attempts before level-1
    count_15m = _count_ip(ip, identifier, now - LEVELS[1]["window"], session)
    return max(0, LEVELS[1]["threshold"] - count_15m)


def record_success(ip: str, identifier: str, session: Session) -> None:
    """Call AFTER a successful authentication. No ban is lifted — just stops counting."""
    pass  # Bans are intentionally not cleared on success


# ── Internal ──────────────────────────────────────────────────────────────────

def _upsert_ban(
    ip: str, identifier: str, level: int, session: Session, now: datetime
) -> bool:
    """Create or upgrade a ban. Returns True if a permanent ban was just triggered."""
    cfg = LEVELS[level]
    banned_until = (now + cfg["duration"]) if cfg["duration"] else None

    existing = _active_ban(ip, identifier, session)
    if existing:
        if level <= existing.level:
            return False  # Never downgrade
        existing.level = level
        existing.banned_until = banned_until
        session.add(existing)
    else:
        session.add(IPBan(ip=ip, identifier=identifier, level=level, banned_until=banned_until))

    return level == 3 and (existing is None or existing.level < 3)


def _lock_client(identifier: str, failure_count: int, session: Session, now: datetime):
    client = session.get(Client, identifier)
    if client and not client.send_locked:
        client.send_locked = True
        client.send_locked_at = now
        session.add(client)
        session.flush()
        email_alert.client_locked(identifier, client.name, failure_count)
