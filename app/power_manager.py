"""
Veille et extinction automatiques (v0.11).

Le Raspberry Pi 4 n'a pas de vraie veille profonde : il est allumé ou
éteint. La boîte enchaîne donc deux paliers quand plus rien ne se passe
(aucun tag posé, rien qui joue, pas de câble USB-C relié à un ordinateur,
personne sur l'administration) :

1. veille légère, après « idle_standby_minutes » (1 min par défaut) :
   processeur au ralenti, lecteur NFC interrogé moins souvent, voyant
   vert qui clignote lentement. Poser un tag la réveille instantanément ;
2. extinction, après « idle_shutdown_minutes » (15 min par défaut) :
   son « bonne nuit » puis arrêt propre. Pour rallumer : le bouton de
   réveil (GPIO 3, broche 5, contre la masse, broche 6), ou
   débrancher/rebrancher l'alimentation.

Le même bouton, la boîte allumée : un appui court la sort de veille, un
appui long (2 s) l'éteint. Il n'est actif que si le lecteur NFC n'est pas
câblé en I2C (la GPIO 3 est alors l'horloge du bus I2C).

Réglages → Énergie règle les deux délais (0 = jamais).
"""

import os
import platform
import threading
import time
from typing import Optional

from app.settings import SettingsManager

CHECK_SECONDS = 5.0
WAKE_PIN = 3
HOLD_SECONDS = 2.0

# Pages relues en boucle par une page restée ouverte : elles ne comptent pas
# comme une présence du parent (sinon un onglet oublié empêcherait la veille).
PASSIVE_ENDPOINTS = {
    "main.api_state", "main.tag_capture_state", "main.control_capture_state",
    "main.usb_state", "static",
}

_settings = SettingsManager()
_lock = threading.Lock()
_tag_present = False
_last_activity = time.monotonic()
_standby = False
_shutting_down = False
_thread: Optional[threading.Thread] = None
_button = None


def set_tag_present(present: bool) -> None:
    global _tag_present
    with _lock:
        _tag_present = present
    note_activity()


def note_activity() -> None:
    """Quelque chose vient de se passer (tag, bouton, page de l'administration)."""
    global _last_activity
    with _lock:
        _last_activity = time.monotonic()
    if _standby:
        _leave_standby()


def is_standby() -> bool:
    return _standby


def state() -> str:
    if _shutting_down:
        return "shutdown"
    return "standby" if _standby else "active"


def idle_seconds() -> float:
    with _lock:
        return time.monotonic() - _last_activity


def _busy() -> bool:
    if _tag_present:
        return True
    try:
        from app.player import player_controller
        if player_controller.get_state()["is_playing"]:
            return True
    except Exception:
        pass
    try:
        from app import usb_gadget
        if usb_gadget.is_transfer_mode():
            return True
    except Exception:
        pass
    return False


def _enter_standby() -> None:
    global _standby
    if _standby:
        return
    _standby = True
    print("[énergie] veille légère.")
    from app import nfc_controller, power_settings
    nfc_controller.set_slow_polling(True)
    power_settings.apply_power_settings(_settings.get_power_hdmi_enabled(), True)


def _leave_standby() -> None:
    global _standby
    if not _standby:
        return
    _standby = False
    print("[énergie] sortie de veille.")
    from app import nfc_controller, power_settings
    nfc_controller.set_slow_polling(False)
    power_settings.apply_saved_power_settings()


def shutdown(reason: str) -> None:
    """Son « bonne nuit », avancement enregistré, puis arrêt du Pi."""
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    print(f"[énergie] extinction ({reason}).")
    try:
        from app import tag_playback
        tag_playback.save_now()
        from app.player import player_controller
        player_controller.shutdown()
    except Exception as exc:
        print(f"[énergie] {exc}")
    try:
        from app import sound_feedback
        sound_feedback.play_goodnight(wait=True)
    except Exception:
        pass
    from app.system_control import shutdown_now
    ok, message = shutdown_now()
    if not ok:
        print(f"[énergie] {message}")
        _shutting_down = False


def _loop() -> None:
    global _last_activity
    while True:
        time.sleep(CHECK_SECONDS)
        try:
            if _busy():
                with _lock:
                    _last_activity = time.monotonic()
                if _standby:
                    _leave_standby()
                continue
            idle_min = idle_seconds() / 60.0
            standby_after = _settings.get_idle_standby_minutes()
            shutdown_after = _settings.get_idle_shutdown_minutes()
            if shutdown_after > 0 and idle_min >= shutdown_after and platform.system() == "Linux":
                shutdown(f"aucune activité depuis {shutdown_after} min")
            elif standby_after > 0 and idle_min >= standby_after:
                _enter_standby()
        except Exception as exc:
            print(f"[énergie] {exc}")


def _start_button() -> None:
    """Bouton réveil / extinction sur la GPIO 3. Ignoré sur PC, ou quand le
    lecteur NFC utilise le bus I2C (qui occupe cette broche)."""
    global _button
    if os.environ.get("CONTAR_NFC_BUS", "spi").lower() == "i2c":
        print("[énergie] lecteur NFC en I2C : bouton de réveil (GPIO 3) non utilisé.")
        return
    try:
        from gpiozero import Button
        _button = Button(WAKE_PIN, pull_up=True, bounce_time=0.05, hold_time=HOLD_SECONDS)
    except Exception as exc:
        print(f"[énergie] bouton de réveil non disponible ({exc}).")
        return
    _button.when_pressed = lambda: note_activity()
    _button.when_held = lambda: threading.Thread(
        target=shutdown, args=("bouton maintenu",), daemon=True
    ).start()
    print(f"[énergie] bouton réveil/extinction prêt (GPIO {WAKE_PIN}, broche 5).")


def start(with_button: bool = True) -> None:
    global _thread
    if _thread is not None:
        return
    note_activity()
    if with_button:
        _start_button()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
