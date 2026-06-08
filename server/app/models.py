from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Client(SQLModel, table=True):
    identifier: str = Field(primary_key=True)
    device_password_hash: str
    send_password_hash: Optional[str] = None
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen: Optional[datetime] = None
    printer_info: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    # Locked when global failure threshold is crossed (all IPs combined)
    send_locked: bool = Field(default=False)
    send_locked_at: Optional[datetime] = None


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    sender: Optional[str] = None
    image_data: Optional[str] = None
    sent_at: datetime = Field(default_factory=datetime.utcnow)


class Delivery(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: int = Field(foreign_key="message.id")
    client_identifier: str = Field(foreign_key="client.identifier")
    status: str = Field(default="pending")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    delivered_at: Optional[datetime] = None
    printed_at: Optional[datetime] = None
    error_msg: Optional[str] = None


class FailedAttempt(SQLModel, table=True):
    """Persistent log of every failed send-password attempt."""
    id: Optional[int] = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    identifier: str = Field(index=True)
    attempted_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class IPBan(SQLModel, table=True):
    """Per-(IP, identifier) ban with escalating levels."""
    id: Optional[int] = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    identifier: str = Field(index=True)
    level: int               # 1 = 1h | 2 = 72h | 3 = permanent
    banned_at: datetime = Field(default_factory=datetime.utcnow)
    banned_until: Optional[datetime] = None   # None → permanent
    active: bool = Field(default=True, index=True)
    lifted_at: Optional[datetime] = None
