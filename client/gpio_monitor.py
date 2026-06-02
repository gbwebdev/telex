"""
GPIO trigger for config ticket reprint.
Short GPIO_PIN (default: GPIO17, physical pin 11) to GND (physical pin 14)
to trigger the callback (e.g. print a new config ticket).
"""

import logging
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)


def start(pin: int, callback: Callable) -> Optional[object]:
    """
    Start monitoring GPIO pin. Returns the Button object (keep reference alive)
    or None if gpiozero is unavailable (non-RPi environment).
    """
    def _run():
        try:
            from gpiozero import Button
            btn = Button(pin, pull_up=True, bounce_time=0.5)
            btn.when_pressed = callback
            log.info("GPIO trigger active on pin %d (short to GND to reprint ticket)", pin)
            # Block this thread forever to keep gpiozero's background threads alive
            threading.Event().wait()
        except ImportError:
            log.info("gpiozero not available — GPIO trigger disabled (normal on non-RPi)")
        except Exception as e:
            log.warning("GPIO setup failed on pin %d: %s", pin, e)

    t = threading.Thread(target=_run, daemon=True, name="gpio-monitor")
    t.start()
    return t
