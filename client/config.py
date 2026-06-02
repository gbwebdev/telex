import json
from pathlib import Path

CONFIG_DIR = Path("/etc/telex")
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "server_url": "",
    "identifier": "",
    "password": "",
    "poll_interval": 60,
    "gpio_ticket_pin": 17,  # Short GPIO17 (pin 11) to GND (pin 14) to reprint ticket
}


def load() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
        except Exception:
            pass

    changed = False
    for k, v in DEFAULTS.items():
        if k not in data:
            data[k] = v
            changed = True
    if changed:
        save(data)
    return data


def save(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def update(**kwargs) -> dict:
    data = load()
    data.update(kwargs)
    save(data)
    return data


def is_configured() -> bool:
    data = load()
    return bool(data.get("server_url") and data.get("identifier") and data.get("password"))
