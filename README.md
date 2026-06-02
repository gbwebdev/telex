# Telex

Self-hosted message-to-thermal-printer system. Send a note from any browser — it prints automatically on a Raspberry Pi connected to a thermal printer.

```
[Web browser] ──→ [FastAPI server] ←── polling ── [RPi Zero W + thermal printer]
```

## Features

- **Anyone can send** — each recipient has a public URL (`/identifier`) protected by a simple password
- **Admin panel** — manage clients, send messages, monitor security
- **Delivery receipts** — ⌛ pending · ✓ received · ✓✓ printed · ✗ failed
- **Offline delivery** — messages queue up and print when the RPi reconnects
- **Fail2ban-style rate limiting** — escalating bans (1h → 72h → permanent) + client lock with admin email alert
- **Headless setup** — no monitor needed; configure the RPi from a browser over the local network
- **Auto-detection** — USB thermal printers detected automatically (Epson TM series, PRP-250, generic ESC/POS)

## Project Structure

```
telex/
├── server/                   # FastAPI server (deploy on your VPS)
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py         # SQLModel tables (Client, Message, Delivery, IPBan, FailedAttempt)
│   │   ├── database.py       # DB init + migrations
│   │   ├── auth.py           # bcrypt password helpers
│   │   ├── rate_limit.py     # DB-backed escalating rate limiter
│   │   ├── email_alert.py    # Admin email notifications
│   │   └── routers/
│   │       ├── admin.py      # Admin API (client management, messages, security)
│   │       ├── client.py     # RPi API (heartbeat, polling, ACK)
│   │       └── public.py     # Public send API (rate-limited, password-verified)
│   │   └── static/
│   │       ├── index.html    # Admin UI
│   │       ├── client.html   # Per-client public send page
│   │       └── send.html     # Generic send page (enter identifier + password)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── requirements.txt
├── client/                   # Raspberry Pi code
│   ├── telex_client.py       # Main daemon (polling + printing)
│   ├── printer.py            # USB printer auto-detection + ESC/POS formatting
│   ├── wifi_manager.py       # WiFi management + configuration hotspot
│   ├── gpio_monitor.py       # GPIO button to reprint config ticket
│   ├── config.py             # Persistent config (/etc/telex/config.json)
│   ├── portal/
│   │   ├── portal.py         # Local config web server (always-on, port 80)
│   │   └── templates/
│   │       └── index.html    # Config portal UI
│   └── requirements.txt
└── deploy/
    ├── install.sh            # RPi installer script
    ├── telex-client.service  # systemd — main daemon
    ├── telex-wifi.service    # systemd — WiFi setup
    └── telex-portal.service  # systemd — config portal
```

---

## Server Deployment

### Prerequisites
- Docker and Docker Compose
- A domain name pointing to your server
- nginx + Let's Encrypt for HTTPS (recommended)

### Install

```bash
cd server/
cp ../.env.example .env
nano .env          # Set ADMIN_API_KEY (required) and SMTP settings (optional)

docker compose up -d
```

The server listens on `127.0.0.1:8000`. Configure nginx to proxy HTTPS traffic to it:

```nginx
server {
    listen 443 ssl;
    server_name telex.example.com;

    ssl_certificate     /etc/letsencrypt/live/telex.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/telex.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ADMIN_API_KEY` | ✓ | Secret key for the admin panel |
| `ADMIN_EMAIL` | — | Email address to receive security alerts |
| `SMTP_HOST` | — | SMTP server hostname |
| `SMTP_PORT` | — | SMTP port (default: 587) |
| `SMTP_USER` | — | SMTP username |
| `SMTP_PASSWORD` | — | SMTP password |
| `SMTP_FROM` | — | From address for alert emails |

---

## Raspberry Pi Setup (headless)

> The RPi Zero W only supports **2.4 GHz** WiFi.

### Supported hardware
- Raspberry Pi Zero W (or any RPi with WiFi)
- USB 80mm ESC/POS thermal printer (two connection modes supported):
  - **USB bulk** (libusb): Epson TM-T20II / TM-T20III / TM-T88V / TM-T20X and generic ESC/POS
  - **Serial over USB / CDC ACM** (`/dev/ttyACM*`): PRP-250 and similar printers

### Step 1 — Flash the SD card

Download **[Raspberry Pi Imager](https://www.raspberrypi.com/software/)**.

1. **OS** → *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (32-bit)**
2. **Storage** → your SD card
3. Click the **⚙ (Edit Settings)** button and fill in:

| Field | Recommended value |
|-------|-------------------|
| Hostname | `telex-arthur` *(or `telex-hugo`, etc.)* |
| SSH | ✓ Enable — password authentication |
| Username | `pi` |
| Password | a password you'll remember |
| WiFi SSID | your 2.4 GHz network |
| WiFi password | your WiFi password |
| WiFi country | your country code |
| Timezone | your timezone |

4. **Save** → **Write** → confirm → wait for the flash to complete.

### Step 2 — First boot

1. Insert the SD card and plug in power
2. Wait **~90 seconds** (first boot: filesystem expansion)
3. Find the RPi's IP address — pick one:
   - Check your router's device list
   - `ping telex-arthur.local` (mDNS — works on macOS/Linux without config)
   - `arp -a | grep -i "b8:27:eb\|dc:a6:32\|e4:5f:01"` (RPi MAC prefixes)

### Step 3 — Install Telex

```bash
ssh pi@telex-arthur.local

git clone https://github.com/gbwebdev/telex.git
cd telex
sudo bash deploy/install.sh
```

The installer prints the portal URL at the end.

### Step 4 — Create the client on the server

In the admin panel (`https://telex.example.com`), go to **CLIENTS → + New**:
- Enter a **name** (display name, e.g. "Arthur") and an **identifier** (URL slug, e.g. `arthur`)
- Optionally set a **send password** (the simple one family members will use)
- **Copy the device password** — it is shown only once

### Step 5 — Configure the RPi

1. Open `http://<rpi-ip>` in your browser (same network)
2. Enter the server URL, identifier, and device password → **Save**
3. The RPi prints a confirmation ticket and starts polling for messages

### No known WiFi on startup

If the SD card wasn't pre-configured with a network:

- The RPi creates a hotspot **`Telex-XXXXXXXX`** (password: `telex1234`)
- Connect to the hotspot from your phone or laptop
- Open `http://192.168.4.1` and configure WiFi
- The RPi reconnects; access the portal at `http://<rpi-ip>` on your normal network

### Reprint the config ticket

- **Via the portal**: `http://<rpi-ip>` → "Reprint ticket" button
- **Physically**: short **GPIO17 (pin 11)** to **GND (pin 14)** with a wire or paperclip

---

## Usage

### Sending a message

**Admin** (full access): `https://telex.example.com` → enter your API key → **SEND** tab

**Family / guests**: `https://telex.example.com/<identifier>` → enter the send password → write your message

The family send page can be bookmarked or shared without exposing admin credentials.

### Delivery status

In the **MESSAGES** tab:

| Icon | Meaning |
|------|---------|
| ⌛ | Pending — RPi hasn't polled yet |
| ✓ | Received by the RPi |
| ✓✓ | Printed successfully |
| ✗ | Print failed (hover for error details) |

Click **↺** on any delivery to resend/reprint.

---

## Security

### Rate limiting

Failures on a client's send page are tracked per IP:

| Threshold | Window | Ban duration |
|-----------|--------|--------------|
| 3 failures | 15 min | 1 hour |
| 5 failures | 1 hour | 72 hours |
| 7 failures | 48 hours | Permanent |

Additionally, if **10 authentication failures** occur for the same client within 24 hours (regardless of IP), the client's send page is **locked** and an email alert is sent to the admin. Bans and locks can be lifted from the **SECURITY** tab.

### Two-password model

| Password | Who uses it | Complexity |
|----------|-------------|------------|
| **Device password** | The RPi (auto-configured) | Auto-generated, complex |
| **Send password** | Family members | Admin-set, simple (e.g. date of birth) |

### Other

- The admin API key is never sent to RPi clients
- Use HTTPS in production so credentials aren't transmitted in plain text

---

## License

MIT
