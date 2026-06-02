"""
WiFi manager for Raspberry Pi Zero W.

Boot sequence:
  1. Wait up to CONNECT_TIMEOUT seconds for a WiFi connection via known networks.
  2. If connected → exit 0 (telex-client.service starts).
  3. If not connected → create a hotspot + start the config portal (exit 1 to
     signal failure; systemd keeps the portal service running).

Uses nmcli (NetworkManager), present by default on Raspberry Pi OS (Bookworm+).
"""

import logging
import subprocess
import sys
import time

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 120  # seconds
POLL_INTERVAL = 5
HOTSPOT_PASSWORD = "telex1234"
HOTSPOT_INTERFACE = "wlan0"


def _run(*args, check=False) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, check=check
    )


def is_connected() -> bool:
    r = _run("nmcli", "-t", "-f", "STATE", "general")
    return "connected" in r.stdout and "disconnected" not in r.stdout


def wait_for_connection(timeout: int = CONNECT_TIMEOUT) -> bool:
    log.info("Waiting up to %ds for WiFi connection…", timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_connected():
            log.info("WiFi connected.")
            return True
        time.sleep(POLL_INTERVAL)
    log.warning("No WiFi connection after %ds.", timeout)
    return False


HOTSPOT_CON_NAME = "telex-hotspot"


def start_hotspot(ssid: str) -> bool:
    log.info("Starting hotspot: SSID=%s", ssid)
    # Remove any stale hotspot connection first
    _run("nmcli", "connection", "delete", HOTSPOT_CON_NAME)
    r = _run(
        "nmcli", "device", "wifi", "hotspot",
        "ssid", ssid,
        "password", HOTSPOT_PASSWORD,
        "ifname", HOTSPOT_INTERFACE,
        "con-name", HOTSPOT_CON_NAME,
    )
    if r.returncode == 0:
        log.info("Hotspot started.")
        return True
    log.error("Failed to start hotspot: %s", r.stderr)
    return False


def stop_hotspot():
    log.info("Stopping hotspot…")
    _run("nmcli", "connection", "delete", HOTSPOT_CON_NAME)


def connect_to_network(ssid: str, password: str) -> bool:
    log.info("Connecting to SSID: %s", ssid)
    r = _run(
        "nmcli", "device", "wifi", "connect", ssid,
        "password", password,
        "ifname", HOTSPOT_INTERFACE,
    )
    if "successfully" in r.stdout.lower():
        log.info("Connected to %s", ssid)
        return True
    log.error("Connection failed: %s", r.stderr or r.stdout)
    return False


def scan_networks() -> list[dict]:
    r = _run("nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list")
    networks = []
    seen = set()
    for line in r.stdout.strip().splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0] and parts[0] not in seen:
            seen.add(parts[0])
            networks.append({
                "ssid": parts[0],
                "signal": int(parts[1]) if parts[1].isdigit() else 0,
                "security": parts[2] if len(parts) > 2 else "",
            })
    return sorted(networks, key=lambda n: -n["signal"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    import config as cfg

    conf = cfg.load()
    uuid = conf["uuid"]
    hotspot_ssid = f"Telex-{uuid[:8]}"

    if wait_for_connection():
        sys.exit(0)

    ok = start_hotspot(hotspot_ssid)
    if not ok:
        log.error("Could not start hotspot. Manual network config needed.")
        sys.exit(2)

    log.info("Hotspot active. Portal should be started by telex-portal.service.")
    # This process exits; systemd starts the portal service independently.
    sys.exit(1)
