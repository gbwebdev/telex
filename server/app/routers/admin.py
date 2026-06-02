import os
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlmodel import Session, select, col

from sqlalchemy import func

from ..auth import generate_password, hash_password, verify_password
from ..database import get_session
from ..models import Client, Delivery, FailedAttempt, IPBan, Message

router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "changeme")
CLIENT_ONLINE_THRESHOLD = timedelta(minutes=2)
IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,28}[a-z0-9]$")


def verify_admin(x_api_key: Optional[str] = Header(None)):
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ─── Clients ─────────────────────────────────────────────────────────────────

@router.post("/clients", status_code=201)
def create_client(
    data: dict,
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    name = str(data.get("name", "")).strip()
    identifier = str(data.get("identifier", "")).strip().lower()
    send_password = str(data.get("send_password", "")).strip()

    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not identifier or not IDENTIFIER_RE.match(identifier):
        raise HTTPException(
            status_code=400,
            detail="identifier must be 2-30 lowercase alphanumeric chars and hyphens",
        )
    if session.get(Client, identifier):
        raise HTTPException(status_code=409, detail="Identifier already exists")

    device_password = generate_password()
    client = Client(
        identifier=identifier,
        name=name,
        device_password_hash=hash_password(device_password),
        send_password_hash=hash_password(send_password) if send_password else None,
    )
    session.add(client)
    session.commit()

    return {
        "identifier": identifier,
        "name": name,
        "device_password": device_password,   # for the RPi — shown ONCE
        "send_password_set": bool(send_password),
    }


@router.get("/clients")
def list_clients(
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    clients = session.exec(select(Client).order_by(col(Client.created_at).desc())).all()
    now = datetime.utcnow()
    return [
        {
            "identifier": c.identifier,
            "name": c.name,
            "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            "online": (
                c.last_seen is not None
                and (now - c.last_seen) < CLIENT_ONLINE_THRESHOLD
            ),
            "has_send_password": bool(c.send_password_hash),
            "send_locked": c.send_locked,
            "send_locked_at": c.send_locked_at.isoformat() if c.send_locked_at else None,
            "printer_info": c.printer_info,
            "ip_address": c.ip_address,
            "mac_address": c.mac_address,
            "created_at": c.created_at.isoformat(),
        }
        for c in clients
    ]


@router.put("/clients/{identifier}")
def update_client(
    identifier: str,
    data: dict,
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    client = session.get(Client, identifier)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if "name" in data:
        client.name = str(data["name"]).strip()[:50]
    session.add(client)
    session.commit()
    return {"identifier": client.identifier, "name": client.name}


@router.post("/clients/{identifier}/reset-device-password")
def reset_device_password(
    identifier: str,
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    """Regenerate the RPi device password. The RPi will need to be reconfigured."""
    client = session.get(Client, identifier)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    password = generate_password()
    client.device_password_hash = hash_password(password)
    session.add(client)
    session.commit()
    return {"identifier": identifier, "device_password": password}  # shown ONCE


@router.post("/clients/{identifier}/set-send-password")
def set_send_password(
    identifier: str,
    data: dict,
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    """Set or update the family send password (the simple one, e.g. date of birth)."""
    client = session.get(Client, identifier)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    password = str(data.get("password", "")).strip()
    if not password:
        raise HTTPException(status_code=400, detail="password is required")
    client.send_password_hash = hash_password(password)
    session.add(client)
    session.commit()
    return {"identifier": identifier, "send_password_set": True}


@router.delete("/clients/{identifier}")
def delete_client(
    identifier: str,
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    client = session.get(Client, identifier)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    for d in session.exec(select(Delivery).where(Delivery.client_identifier == identifier)).all():
        session.delete(d)
    session.delete(client)
    session.commit()
    return {"deleted": identifier}


# ─── Security ────────────────────────────────────────────────────────────────

@router.get("/security")
def get_security(
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    now = datetime.utcnow()
    since_24h = now - timedelta(hours=24)

    locked_clients = session.exec(
        select(Client).where(Client.send_locked == True)
    ).all()

    active_bans = session.exec(
        select(IPBan)
        .where(IPBan.active == True)
        .order_by(col(IPBan.level).desc(), col(IPBan.banned_at).desc())
    ).all()

    recent_attempts = session.exec(
        select(FailedAttempt)
        .where(FailedAttempt.attempted_at >= since_24h)
        .order_by(col(FailedAttempt.attempted_at).desc())
        .limit(500)
    ).all()

    # Resolve client names for bans and attempts
    client_names = {
        c.identifier: c.name
        for c in session.exec(select(Client)).all()
    }

    return {
        "locked_clients": [
            {
                "identifier": c.identifier,
                "name": c.name,
                "locked_at": c.send_locked_at.isoformat() if c.send_locked_at else None,
            }
            for c in locked_clients
        ],
        "active_bans": [
            {
                "id": b.id,
                "ip": b.ip,
                "identifier": b.identifier,
                "client_name": client_names.get(b.identifier, b.identifier),
                "level": b.level,
                "banned_at": b.banned_at.isoformat(),
                "banned_until": b.banned_until.isoformat() if b.banned_until else None,
            }
            for b in active_bans
        ],
        "recent_attempts": [
            {
                "ip": a.ip,
                "identifier": a.identifier,
                "client_name": client_names.get(a.identifier, a.identifier),
                "attempted_at": a.attempted_at.isoformat(),
            }
            for a in recent_attempts
        ],
    }


@router.post("/security/bans/{ban_id}/lift")
def lift_ban(
    ban_id: int,
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    ban = session.get(IPBan, ban_id)
    if not ban:
        raise HTTPException(status_code=404, detail="Ban not found")
    ban.active = False
    ban.lifted_at = datetime.utcnow()
    session.add(ban)
    session.commit()
    return {"lifted": True, "id": ban_id}


@router.post("/clients/{identifier}/unlock")
def unlock_client(
    identifier: str,
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    client = session.get(Client, identifier)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.send_locked = False
    client.send_locked_at = None
    session.add(client)
    session.commit()
    return {"unlocked": True, "identifier": identifier}


# ─── Messages ────────────────────────────────────────────────────────────────

@router.post("/messages")
def send_message(
    data: dict,
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    return _create_message(data, session)


@router.get("/messages")
def list_messages(
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    messages = session.exec(
        select(Message).order_by(col(Message.sent_at).desc()).limit(200)
    ).all()
    return [_format_message(msg, session) for msg in messages]


@router.post("/deliveries/{delivery_id}/resend")
def resend(
    delivery_id: int,
    session: Session = Depends(get_session),
    _=Depends(verify_admin),
):
    delivery = session.get(Delivery, delivery_id)
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    delivery.status = "pending"
    delivery.delivered_at = None
    delivery.printed_at = None
    delivery.error_msg = None
    session.add(delivery)
    session.commit()
    return {"status": "resent"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _create_message(data: dict, session: Session) -> dict:
    content = str(data.get("content", "")).strip()
    targets = data.get("client_identifiers") or []

    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    if len(content) > 500:
        raise HTTPException(status_code=400, detail="content exceeds 500 characters")
    if not targets:
        raise HTTPException(status_code=400, detail="at least one recipient required")

    message = Message(content=content)
    session.add(message)
    session.flush()

    deliveries = []
    for ident in targets:
        if not session.get(Client, ident):
            raise HTTPException(status_code=404, detail=f"Client '{ident}' not found")
        d = Delivery(message_id=message.id, client_identifier=ident)
        session.add(d)
        session.flush()
        deliveries.append({"delivery_id": d.id, "client_identifier": ident})

    session.commit()
    return {
        "message_id": message.id,
        "sent_at": message.sent_at.isoformat(),
        "deliveries": deliveries,
    }


def _format_message(msg: Message, session: Session) -> dict:
    deliveries = session.exec(
        select(Delivery).where(Delivery.message_id == msg.id)
    ).all()
    clients = {
        d.client_identifier: session.get(Client, d.client_identifier)
        for d in deliveries
    }
    return {
        "id": msg.id,
        "content": msg.content,
        "sent_at": msg.sent_at.isoformat(),
        "deliveries": [
            {
                "id": d.id,
                "client_identifier": d.client_identifier,
                "client_name": (
                    clients[d.client_identifier].name
                    if clients.get(d.client_identifier)
                    else None
                ),
                "status": d.status,
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
                "printed_at": d.printed_at.isoformat() if d.printed_at else None,
                "error_msg": d.error_msg,
            }
            for d in deliveries
        ],
    }
