"""
Les deux voyants de la boîte (v0.11), à la place de l'écran.

    vert   allumé          la boîte est en marche
           clignote vite   reliée à un ordinateur (transfert USB-C)
           clignote lent   veille légère
    rouge  allumé          une histoire ou une musique est en train de jouer

Câblage : chaque LED avec sa résistance (220 à 330 Ω) entre la broche et la
masse. Vert sur GPIO 23 (broche 16), rouge sur GPIO 24 (broche 18) ; masse
broche 14 ou 20. Broches modifiables par CONTAR_LED_GREEN / CONTAR_LED_RED.
Sans LED branchée (ou sur PC), ce module ne fait rien.
"""

import os
import threading
import time
from typing import Optional

GREEN_PIN = int(os.environ.get("CONTAR_LED_GREEN", "23"))
RED_PIN = int(os.environ.get("CONTAR_LED_RED", "24"))
TICK = 0.1

_green = None
_red = None
_thread: Optional[threading.Thread] = None


def _green_should_be_on(now: float) -> bool:
    from app import power_manager, usb_gadget
    if power_manager.state() == "shutdown":
        return False
    if usb_gadget.is_transfer_mode():
        return (now % 0.5) < 0.25           # 2 clignotements par seconde
    if power_manager.is_standby():
        return (now % 3.0) < 0.3            # un éclat toutes les 3 s
    return True


def _red_should_be_on() -> bool:
    from app.player import player_controller
    try:
        return bool(player_controller.get_state()["is_playing"])
    except Exception:
        return False


def _loop() -> None:
    while True:
        now = time.monotonic()
        try:
            green, red = _green_should_be_on(now), _red_should_be_on()
            if _green is not None and _green.is_lit != green:
                _green.on() if green else _green.off()
            if _red is not None and _red.is_lit != red:
                _red.on() if red else _red.off()
        except Exception as exc:
            print(f"[voyants] {exc}")
            time.sleep(5)
        time.sleep(TICK)


def start() -> None:
    global _green, _red, _thread
    if _thread is not None:
        return
    try:
        from gpiozero import LED
        _green = LED(GREEN_PIN)
        _red = LED(RED_PIN)
        _green.on()
    except Exception as exc:
        print(f"[voyants] non disponibles ({exc}).")
        return
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    print(f"Voyants actifs : vert GPIO {GREEN_PIN}, rouge GPIO {RED_PIN}.")
