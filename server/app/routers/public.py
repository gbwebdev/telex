import base64

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from ..auth import verify_password
from ..database import get_session
from ..models import Client, Delivery, Message
from .. import rate_limit

router = APIRouter(prefix="/api/public", tags=["public"])


def _real_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host or "unknown"


@router.get("/{identifier}")
def get_client_info(identifier: str, session: Session = Depends(get_session)):
    client = session.get(Client, identifier)
    if not client or not client.send_password_hash:
        raise HTTPException(status_code=404, detail="Destinataire introuvable")
    # Don't reveal lock status — just surface a generic error
    if client.send_locked:
        raise HTTPException(
            status_code=503,
            detail="Ce service est temporairement indisponible. Contactez l'administrateur.",
        )
    return {"name": client.name}


@router.post("/{identifier}/send")
def public_send(
    identifier: str,
    data: dict,
    request: Request,
    session: Session = Depends(get_session),
):
    ip = _real_ip(request)

    try:
        rate_limit.check_allowed(ip, identifier, session)
    except rate_limit.RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=e.message)

    client = session.get(Client, identifier)
    if not client or not client.send_password_hash:
        raise HTTPException(status_code=404, detail="Destinataire introuvable")

    password = str(data.get("password", ""))
    content = str(data.get("content", "")).strip()
    sender = (str(data.get("sender", "")).strip() or None)
    if sender:
        sender = sender[:50]
    image_data = data.get("image") or None

    if not verify_password(password, client.send_password_hash):
        remaining = rate_limit.record_failure(ip, identifier, session)
        if remaining == 0:
            raise HTTPException(
                status_code=429,
                detail="Mot de passe incorrect. Accès bloqué suite à trop de tentatives.",
            )
        raise HTTPException(
            status_code=401,
            detail=f"Mot de passe incorrect. {remaining} tentative(s) restante(s) avant blocage.",
        )

    if not content:
        raise HTTPException(status_code=400, detail="Le message est vide")
    if len(content) > 500:
        raise HTTPException(status_code=400, detail="Message trop long (500 caractères max)")

    if image_data:
        if len(image_data) > 600_000:
            raise HTTPException(status_code=400, detail="Image trop grande")
        try:
            base64.b64decode(image_data, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Image invalide")

    rate_limit.record_success(ip, identifier, session)

    message = Message(content=content, sender=sender, image_data=image_data)
    session.add(message)
    session.flush()
    session.add(Delivery(message_id=message.id, client_identifier=identifier))
    session.commit()

    return {"sent": True, "name": client.name}
