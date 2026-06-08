#!/usr/bin/env python3
"""
Telex client daemon.

- Registers with the server using identifier + password
- Polls every poll_interval seconds for new messages and prints them
- Prints a config ticket when the network IP changes (new network)
- GPIO trigger reprints the config ticket on demand
"""

import json
import logging
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests

import config as cfg
import gpio_monitor
import printer as prn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("telex")

STATE_FILE = Path("/etc/telex/state.json")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s, indent=2))


def get_ip() -> str:
    try:
        r = subprocess.run(
            ["ip", "-4", "addr", "show", "wlan0"],
            capture_output=True, text=True
        )
        for line in r.stdout.splitlines():
            if "inet " in line:
                return line.strip().split()[1].split("/")[0]
    except Exception:
        pass
    # Fallback via socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return ""


def get_mac() -> str:
    try:
        return Path("/sys/class/net/wlan0/address").read_text().strip()
    except Exception:
        return ""


def api(conf: dict, method: str, path: str, **kwargs) -> requests.Response:
    url = conf["server_url"].rstrip("/") + path
    headers = {
        "X-Client-ID": conf["identifier"],
        "X-Client-Secret": conf["password"],
    }
    return requests.request(method, url, headers=headers, timeout=30, **kwargs)


def register(conf: dict, printer_info: dict | None, ip: str, mac: str) -> bool:
    try:
        body = {"ip_address": ip, "mac_address": mac}
        if printer_info:
            body["printer_info"] = json.dumps(printer_info)
        r = api(conf, "POST", "/api/clients/register", json=body)
        if r.status_code == 200:
            return True
        log.warning("Register returned %d: %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        log.warning("Register failed: %s", e)
        return False


def poll(conf: dict) -> tuple[list[dict], str]:
    r = api(conf, "GET", "/api/clients/messages")
    r.raise_for_status()
    data = r.json()
    return data.get("messages", []), data.get("name", "")


def ack(conf: dict, delivery_id: int, ok: bool, error: str = ""):
    path = f"/api/clients/deliveries/{delivery_id}/{'printed' if ok else 'failed'}"
    try:
        api(conf, "POST", path, json=({"error": error} if not ok else {}))
    except Exception as e:
        log.warning("ACK failed for delivery #%d: %s", delivery_id, e)


def main():
    conf = cfg.load()
    state = load_state()

    p, printer_info = prn.detect_printer()
    ip = get_ip()
    mac = get_mac()

    def do_print_config_ticket():
        current_ip = get_ip()
        current_mac = get_mac()
        current_conf = cfg.load()
        if p:
            try:
                prn.print_config_ticket(
                    p,
                    identifier=current_conf.get("identifier", "?"),
                    ip=current_ip or "?",
                    mac=current_mac or "?",
                    server_url=current_conf.get("server_url", ""),
                    name=state.get("server_name", ""),
                )
                log.info("Config ticket printed.")
            except Exception as e:
                log.error("Config ticket print failed: %s", e)
        else:
            log.warning("No printer for config ticket.")

    # GPIO trigger
    gpio_pin = conf.get("gpio_ticket_pin", 17)
    gpio_monitor.start(gpio_pin, do_print_config_ticket)

    # Print config ticket if not configured yet
    if not cfg.is_configured():
        log.info("Not configured. Printing setup ticket.")
        if p and ip:
            try:
                prn.print_unconfigured_ticket(p, ip, mac)
            except Exception as e:
                log.error("Setup ticket failed: %s", e)
        log.info("Waiting for configuration via http://%s …", ip or "?")
        # Poll config every 30s until configured
        while not cfg.is_configured():
            time.sleep(30)
            conf = cfg.load()
        log.info("Configuration detected, starting.")

    # Print config ticket when IP changes (new network)
    if ip and ip != state.get("last_ip"):
        log.info("Network changed (IP: %s → %s), printing config ticket.", state.get("last_ip"), ip)
        do_print_config_ticket()
        state["last_ip"] = ip
        save_state(state)

    interval = conf.get("poll_interval", 60)
    log.info("Starting polling loop (interval=%ds, identifier=%s)", interval, conf.get("identifier"))

    while True:
        conf = cfg.load()

        # Re-detect printer if lost
        if p is None:
            p, printer_info = prn.detect_printer()
            if p:
                log.info("Printer detected: %s", printer_info.get("name"))

        current_ip = get_ip()
        if current_ip and current_ip != state.get("last_ip"):
            state["last_ip"] = current_ip
            save_state(state)
            do_print_config_ticket()

        try:
            messages, server_name = poll(conf)
            if server_name:
                state["server_name"] = server_name
                save_state(state)

            # Re-register to update IP/MAC/printer on server
            register(conf, printer_info, current_ip, get_mac())

            if messages:
                log.info("%d message(s) to print.", len(messages))

            for msg in messages:
                did = msg["delivery_id"]
                try:
                    if p is None:
                        raise RuntimeError("No printer")
                    prn.print_message(
                        p, msg["content"], msg["sent_at"], server_name,
                        sender=msg.get("sender"),
                        image_data=msg.get("image_data"),
                    )
                    ack(conf, did, ok=True)
                    log.info("Printed delivery #%d", did)
                except Exception as e:
                    log.error("Print failed #%d: %s", did, e)
                    ack(conf, did, ok=False, error=str(e))

        except requests.RequestException as e:
            log.warning("Server unreachable: %s", e)
        except Exception as e:
            log.error("Error: %s", e)

        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
