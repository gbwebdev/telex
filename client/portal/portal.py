#!/usr/bin/env python3
"""
Telex configuration server — always running on the RPi.

Accessible at http://<rpi-ip> when on local WiFi,
or at http://192.168.4.1 when in hotspot mode.

Handles:
  - WiFi configuration
  - Telex server URL / identifier / password
  - Name update (syncs to server)
  - Manual config ticket reprint
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as cfg
import printer as prn
import wifi_manager as wm

log = logging.getLogger("portal")
app = Flask(__name__)


# ── Network helpers ───────────────────────────────────────────────────────────

def get_ip() -> str:
    try:
        r = subprocess.run(["ip", "-4", "addr", "show", "wlan0"], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if "inet " in line:
                return line.strip().split()[1].split("/")[0]
    except Exception:
        pass
    return ""


def get_mac() -> str:
    try:
        return Path("/sys/class/net/wlan0/address").read_text().strip()
    except Exception:
        return ""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    conf = cfg.load()
    return render_template("index.html", conf=conf)


@app.route("/api/status")
def status():
    import requests as req
    conf = cfg.load()
    ip = get_ip()
    mac = get_mac()
    connected = wm.is_connected()

    server_ok = False
    server_name = None
    if cfg.is_configured():
        try:
            url = conf["server_url"].rstrip("/") + "/api/clients/messages"
            r = req.get(url, headers={
                "X-Client-ID": conf["identifier"],
                "X-Client-Secret": conf["password"],
            }, timeout=5)
            server_ok = r.status_code == 200
            if server_ok:
                server_name = r.json().get("name")
        except Exception:
            pass

    return jsonify({
        "configured": cfg.is_configured(),
        "wifi": connected,
        "server_ok": server_ok,
        "ip": ip,
        "mac": mac,
        "identifier": conf.get("identifier", ""),
        "server_url": conf.get("server_url", ""),
        "server_name": server_name,
    })


@app.route("/api/wifi/scan")
def wifi_scan():
    return jsonify(wm.scan_networks())


@app.route("/api/wifi/connect", methods=["POST"])
def wifi_connect():
    data = request.json or {}
    ssid = str(data.get("ssid", "")).strip()
    password = str(data.get("password", ""))
    if not ssid:
        return jsonify({"success": False, "error": "SSID manquant"}), 400

    wm.stop_hotspot()
    ok = wm.connect_to_network(ssid, password)
    if ok:
        return jsonify({"success": True, "ip": get_ip()})
    wm.start_hotspot(f"Telex-{cfg.load().get('identifier', 'setup')[:8]}")
    return jsonify({"success": False, "error": "Connexion échouée. Vérifiez le mot de passe."}), 400


@app.route("/api/config", methods=["POST"])
def update_config():
    data = request.json or {}
    updates = {}
    for key in ("server_url", "identifier", "password"):
        val = str(data.get(key, "")).strip()
        if val:
            updates[key] = val
    if updates:
        cfg.update(**updates)
    return jsonify({"success": True, "config": cfg.load()})


@app.route("/api/name", methods=["POST"])
def update_name():
    import requests as req
    data = request.json or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"success": False, "error": "Nom requis"}), 400

    conf = cfg.load()
    if not cfg.is_configured():
        return jsonify({"success": False, "error": "Client non configuré"}), 400

    try:
        r = req.put(
            conf["server_url"].rstrip("/") + "/api/clients/name",
            json={"name": name},
            headers={
                "X-Client-ID": conf["identifier"],
                "X-Client-Secret": conf["password"],
            },
            timeout=10,
        )
        if r.status_code == 200:
            return jsonify({"success": True, "name": r.json().get("name")})
        return jsonify({"success": False, "error": r.json().get("detail", "Erreur serveur")}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ticket", methods=["POST"])
def print_ticket():
    conf = cfg.load()
    ip = get_ip()
    mac = get_mac()
    p, _ = prn.detect_printer()
    if not p:
        return jsonify({"success": False, "error": "Imprimante non détectée"}), 500
    try:
        if cfg.is_configured():
            prn.print_config_ticket(p, conf["identifier"], ip or "?", mac or "?", conf.get("server_url", ""))
        else:
            prn.print_unconfigured_ticket(p, ip or "?", mac or "?")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log.info("Config portal starting on port 80…")
    app.run(host="0.0.0.0", port=80, debug=False)
