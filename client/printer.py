"""
Auto-detects a USB thermal printer and prints ESC/POS formatted messages.

Two connection modes are supported:
  - USB bulk (libusb/pyusb): Epson TM series and most ESC/POS printers.
    Requires usblp kernel module to be blacklisted (see deploy/install.sh).
  - Serial over USB (CDC ACM): printers that present as /dev/ttyACM*.
    Requires the pi user to be in the dialout group.
"""

import base64
import glob
import json
import logging
import textwrap
from datetime import datetime
from io import BytesIO

log = logging.getLogger(__name__)

KNOWN_USB_PRINTERS = [
    (0x04B8, 0x0202, "Epson TM-T20II"),
    (0x04B8, 0x0232, "Epson TM-T20III"),
    (0x04B8, 0x0301, "Epson TM-T88V"),
    (0x04B8, 0x0E15, "Epson TM-T20X"),
    (0x0416, 0x5011, "Generic ESC/POS (WH-A10)"),
    (0x1504, 0x0006, "Generic ESC/POS"),
    (0x0FE6, 0x811E, "Generic ESC/POS (ICS)"),
    (0x28E9, 0x0289, "Generic ESC/POS"),
]

PAPER_WIDTH = 42  # characters at 80mm / 12cpi


def detect_printer():
    """Return (printer_instance, info_dict) or (None, None).

    Detection order:
      1. Known USB printers by VID/PID (bulk mode, libusb)
      2. Any USB device with printer interface class 7 (bulk mode, libusb)
      3. CDC ACM serial-over-USB devices (/dev/ttyACM*)
    """
    # ── 1 & 2: USB bulk mode ─────────────────────────────────────────────────
    try:
        import usb.core
        from escpos.printer import Usb

        for vid, pid, name in KNOWN_USB_PRINTERS:
            if usb.core.find(idVendor=vid, idProduct=pid):
                log.info("Found: %s (%04x:%04x)", name, vid, pid)
                try:
                    return Usb(vid, pid), {"name": name, "mode": "usb", "vid": hex(vid), "pid": hex(pid)}
                except Exception as e:
                    log.warning("Could not open %s: %s", name, e)

        for dev in usb.core.find(find_all=True):
            try:
                for cfg in dev:
                    for intf in cfg:
                        if intf.bInterfaceClass == 7:
                            vid, pid = dev.idVendor, dev.idProduct
                            name = f"USB Printer ({vid:04x}:{pid:04x})"
                            log.info("Found generic USB: %s", name)
                            return Usb(vid, pid), {"name": name, "mode": "usb", "vid": hex(vid), "pid": hex(pid)}
            except Exception:
                continue

    except ImportError:
        log.warning("pyusb/python-escpos not available, skipping USB bulk detection")
    except Exception as e:
        log.error("USB scan error: %s", e)

    # ── 3: CDC ACM / serial-over-USB ─────────────────────────────────────────
    # Printers like PRP-250 present as /dev/ttyACM* instead of USB bulk.
    try:
        from escpos.printer import Serial

        for dev_path in sorted(glob.glob("/dev/ttyACM*")):
            log.info("Trying serial printer: %s", dev_path)
            try:
                p = Serial(dev_path, baudrate=9600)
                name = f"Serial Printer ({dev_path})"
                return p, {"name": name, "mode": "serial", "port": dev_path}
            except Exception as e:
                log.warning("Could not open %s: %s", dev_path, e)

    except ImportError:
        log.warning("pyserial not available, skipping serial detection")
    except Exception as e:
        log.error("Serial scan error: %s", e)

    log.warning("No printer found")
    return None, None


def _hr(p, char="─"):
    p.text(char * PAPER_WIDTH + "\n")


def print_message(p, content: str, sent_at: str, client_name: str = "",
                  sender: str = None, image_data: str = None):
    """Print an incoming message."""
    try:
        ts = datetime.fromisoformat(sent_at).strftime("%d/%m/%Y %H:%M")
    except Exception:
        ts = sent_at

    p.set(align="center", bold=True)
    p.text("✦ TELEX ✦\n")
    p.set(align="center", bold=False)
    _hr(p)

    p.set(align="left")
    p.text(f"Recu le : {ts}\n")
    if client_name:
        p.text(f"Pour    : {client_name}\n")
    if sender:
        p.text(f"De      : {sender}\n")
    _hr(p)
    p.text("\n")

    p.set(align="left")
    for line in textwrap.wrap(content, width=PAPER_WIDTH) or [""]:
        p.text(line + "\n")
    p.text("\n")

    if image_data:
        try:
            from PIL import Image
            img = Image.open(BytesIO(base64.b64decode(image_data))).convert("1")
            p.set(align="center")
            p.image(img)
            p.text("\n")
        except Exception as e:
            log.error("Image print failed: %s", e)

    _hr(p)
    p.text("\n\n\n")
    p.cut()


def print_config_ticket(p, identifier: str, ip: str, mac: str, server_url: str, name: str = ""):
    """Print a configuration/info ticket with IP, MAC and QR code."""
    import qrcode

    config_url = f"http://{ip}"

    p.set(align="center", bold=True)
    p.text("TELEX\n")
    p.set(align="center", bold=False)
    _hr(p)
    p.set(align="center")
    p.text("CONFIGURATION\n")
    p.text(datetime.now().strftime("%d/%m/%Y %H:%M") + "\n\n")

    if name:
        p.set(align="center", bold=True)
        p.text(name.upper() + "\n")
        p.set(align="center", bold=False)

    p.set(align="left")
    p.text(f"Identifiant : {identifier}\n")
    p.text(f"Adresse MAC : {mac}\n")
    p.text(f"Adresse IP  : {ip}\n")
    p.text(f"Serveur     : {server_url or 'non configuré'}\n\n")

    # QR code → config web server
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(config_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    p.set(align="center")
    p.image(img)
    p.text("\n")

    _hr(p)
    p.set(align="center")
    p.text(f"Interface de config :\n{config_url}\n")
    _hr(p)
    p.text("\n\n\n")
    p.cut()


def print_unconfigured_ticket(p, ip: str, mac: str):
    """Print a ticket when the client is not yet configured."""
    p.set(align="center", bold=True)
    p.text("TELEX\n")
    p.set(align="center", bold=False)
    _hr(p)
    p.set(align="center")
    p.text("CONFIGURATION REQUISE\n\n")

    p.set(align="left")
    p.text(f"Adresse IP  : {ip}\n")
    p.text(f"Adresse MAC : {mac}\n\n")
    p.text("Rendez-vous sur :\n")
    p.set(align="center", bold=True)
    p.text(f"http://{ip}\n")
    p.set(align="center", bold=False)
    p.text("\npour configurer ce Telex.\n")
    _hr(p)
    p.text("\n\n\n")
    p.cut()


def get_printer_info_json(info: dict) -> str:
    return json.dumps(info)
