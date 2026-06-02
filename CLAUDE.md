# Telex — CLAUDE.md

## What this project is

Telex is a self-hosted message-to-thermal-printer system. Family members send short text messages from a browser; the message auto-prints on a Raspberry Pi Zero W connected to a USB thermal printer. Designed for children — security is a primary concern.

## Architecture

```
[Browser] → POST /api/public/{identifier}/send
                 ↓
         [FastAPI server]  ← Docker on a VPS
                 ↓
         [SQLite via SQLModel]
                 ↑
         [RPi Zero W daemon]  polls every 60s, prints via python-escpos
```

- **Server**: `server/` — FastAPI + SQLModel + SQLite, deployed with Docker Compose
- **Client**: `client/` — Python daemon running on Raspberry Pi Zero W
- **Deploy**: `deploy/` — systemd services + install script for headless RPi setup

## Key design decisions

### Two-password model
- **Device password**: auto-generated (`secrets.token_urlsafe(12)`), stored hashed, used by the RPi daemon (`X-Client-Secret` header). Never shown to family.
- **Send password**: admin-set, simple (e.g. date of birth), used by family on the public send page. Can be left unset to disable public sends.

### Public send pages
Each client has a dedicated URL at `/{identifier}` (e.g. `/arthur`). The page is served from `server/app/static/client.html` and calls `/api/public/{identifier}/send`. No admin credentials involved.

### Rate limiting philosophy
This system is used by children. Rate limiting is intentionally strict:
- 3 failures / 15 min → 1h ban (per IP)
- 5 failures / 1h → 72h ban
- 7 failures / 48h → permanent ban
- 10 total failures / 24h (any IP) → client locked + admin email alert

Bans are DB-backed (`IPBan`, `FailedAttempt` tables) — they survive server restarts. Bans are never auto-downgraded, only admin-liftable.

### Delivery receipts
`Delivery.status`: `pending` → `delivered` (RPi polled it) → `printed` or `failed`

## Data model (summary)

```python
Client(identifier PK, name, device_password_hash, send_password_hash,
       last_seen, ip_address, mac_address, printer_info,
       send_locked, send_locked_at, created_at)

Message(id, content, sent_at)
Delivery(id, message_id, client_identifier FK, status,
         created_at, delivered_at, printed_at, error_msg)

FailedAttempt(id, ip, identifier, attempted_at)
IPBan(id, ip, identifier, level, banned_at, banned_until, active, lifted_at)
```

## API surface

| Auth | Prefix | Used by |
|------|--------|---------|
| `X-Api-Key: ADMIN_API_KEY` | `/api/admin/*` | Admin UI |
| `X-Client-ID` + `X-Client-Secret` | `/api/clients/*` | RPi daemon |
| None (rate-limited + send password) | `/api/public/*` | Family browsers |

## RPi client services (systemd)

1. `telex-portal.service` — always-on local config web server on port 80
2. `telex-wifi.service` — oneshot: joins known network or starts hotspot `Telex-XXXXXXXX`
3. `telex-client.service` — main polling daemon, starts after `network-online.target`

Config lives at `/etc/telex/config.json`:
```json
{"server_url": "https://...", "identifier": "arthur", "password": "...", "poll_interval": 60, "gpio_ticket_pin": 17}
```

## Printer detection (`client/printer.py`)

Two connection modes, tried in order:

1. **USB bulk (libusb)** — `escpos.printer.Usb(vid, pid)`. Requires `usblp` kernel module to be blacklisted (it claims the device before libusb can). `install.sh` writes `/etc/modprobe.d/telex-printers.conf` to blacklist it.

2. **CDC ACM / serial-over-USB** — `escpos.printer.Serial('/dev/ttyACMx')`. Printers like PRP-250 present as a virtual serial port instead of a USB bulk device. Requires the `pi` user to be in the `dialout` group (set by `install.sh`).

`printer_info` stored on the server includes a `mode` field (`"usb"` or `"serial"`) to help diagnose issues remotely.

## Coding conventions

- Python, no type annotations on function bodies (SQLModel fields are typed)
- FastAPI routers in `server/app/routers/`
- DB migrations are idempotent `ALTER TABLE ... ADD COLUMN` with `try/except` in `database.py`
- Email alerts run in daemon threads — if SMTP is unconfigured, log a warning and skip silently
- No comments unless the WHY is non-obvious

## Deployment

```bash
cd server/
cp ../.env.example .env && nano .env   # set ADMIN_API_KEY at minimum
docker compose up -d
```

Server binds to `127.0.0.1:8000` — nginx + Let's Encrypt handles TLS.
`ProxyHeadersMiddleware` is configured to trust `127.0.0.1` for real-IP extraction.
