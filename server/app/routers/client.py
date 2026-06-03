from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlmodel import Session, select

from ..auth import verify_password
from ..database import get_session
from ..models import Client, Delivery, Message
from .. import rate_limit

router = APIRouter(prefix="/api/clients", tags=["client"])


def _real_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host or "unknown"


def authenticate_client(
    request: Request,
    x_client_id: Optional[str] = Header(None),
    x_client_secret: Optional[str] = Header(None),
    session: Session = Depends(get_session),
) -> Client:
    if not x_client_id or not x_client_secret:
        raise HTTPException(
            status_code=401,
            detail="X-Client-ID and X-Client-Secret headers required",
        )

    ip = _real_ip(request)

    try:
        rate_limit.check_allowed(ip, x_client_id, session)
    except rate_limit.RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=e.message)

    client = session.exec(
        select(Client).where(Client.identifier == x_client_id)
    ).first()
    if not client or not verify_password(x_client_secret, client.device_password_hash):
        rate_limit.record_failure(ip, x_client_id, session)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    rate_limit.record_success(ip, x_client_id, session)
    return client


@router.post("/register")
def register(
    data: dict,
    client: Client = Depends(authenticate_client),
    session: Session = Depends(get_session),
):
    client.last_seen = datetime.utcnow()
    if "printer_info" in data:
        client.printer_info = data["printer_info"]
    if "ip_address" in data:
        client.ip_address = data["ip_address"]
    if "mac_address" in data:
        client.mac_address = data["mac_address"]
    session.add(client)
    session.commit()
    return {"registered": True, "name": client.name}


@router.get("/messages")
def get_messages(
    client: Client = Depends(authenticate_client),
    session: Session = Depends(get_session),
):
    client.last_seen = datetime.utcnow()
    session.add(client)

    pending = session.exec(
        select(Delivery).where(
            Delivery.client_identifier == client.identifier,
            Delivery.status == "pending",
        )
    ).all()

    messages = []
    for delivery in pending:
        msg = session.get(Message, delivery.message_id)
        if msg:
            delivery.status = "delivered"
            delivery.delivered_at = datetime.utcnow()
            session.add(delivery)
            messages.append(
                {
                    "delivery_id": delivery.id,
                    "message_id": msg.id,
                    "content": msg.content,
                    "sent_at": msg.sent_at.isoformat(),
                }
            )

    session.commit()
    return {"messages": messages, "name": client.name}


@router.post("/deliveries/{delivery_id}/printed")
def ack_printed(
    delivery_id: int,
    client: Client = Depends(authenticate_client),
    session: Session = Depends(get_session),
):
    delivery = session.get(Delivery, delivery_id)
    if not delivery or delivery.client_identifier != client.identifier:
        raise HTTPException(status_code=404, detail="Delivery not found")
    delivery.status = "printed"
    delivery.printed_at = datetime.utcnow()
    session.add(delivery)
    session.commit()
    return {"status": "printed"}


@router.post("/deliveries/{delivery_id}/failed")
def ack_failed(
    delivery_id: int,
    data: dict,
    client: Client = Depends(authenticate_client),
    session: Session = Depends(get_session),
):
    delivery = session.get(Delivery, delivery_id)
    if not delivery or delivery.client_identifier != client.identifier:
        raise HTTPException(status_code=404, detail="Delivery not found")
    delivery.status = "failed"
    delivery.error_msg = str(data.get("error", "Unknown error"))[:500]
    session.add(delivery)
    session.commit()
    return {"status": "failed"}


@router.put("/name")
def update_name(
    data: dict,
    client: Client = Depends(authenticate_client),
    session: Session = Depends(get_session),
):
    name = str(data.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    client.name = name[:50]
    session.add(client)
    session.commit()
    return {"name": client.name}
