"""
Le câble USB-C (v0.11) : la boîte reliée à un ordinateur.

Le périphérique lui-même (carte réseau + disque de dépôt) est créé au
démarrage par bin/usb-gadget.sh (service contar-usb-gadget). Ce module
surveille l'état du port chaque seconde :

- « configured » : un ordinateur l'utilise. La boîte passe en MODE
  TRANSFERT : la lecture se met en pause (avancement enregistré), les tags
  ne lancent plus rien (sauf pour les associer depuis l'administration),
  voyant vert qui clignote, son « branché ». L'administration est alors
  ouverte à l'ordinateur sur http://10.55.0.1 ;
- le disque de dépôt éjecté par l'ordinateur : la boîte reprend le disque,
  range ce qu'il contient (app/depot_import.py), joue un carillon, vide le
  disque et le remet à disposition. Débranché sans éjecter, la boîte (qui
  s'éteint alors, faute de courant) range le dépôt au démarrage suivant.

Alimentation : la boîte est alimentée par ce même port. Branchée sur un
ordinateur, c'est lui qui la nourrit, parfois trop faiblement (port USB 2,
câble USB-A). La boîte le détecte (« sous-tension », vcgencmd) et le
signale dans l'administration.

Sur PC, ou sans contrôleur USB-C en mode périphérique, rien ne se passe ;
CONTAR_USB_SIMU=1 simule un ordinateur branché (tests de l'administration).
"""

import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

HELPER = os.environ.get(
    "CONTAR_USB_HELPER", str(Path(__file__).resolve().parent.parent / "bin" / "usb-gadget.sh")
)
POLL_SECONDS = 1.0
UDC_ROOT = Path("/sys/class/udc")
LUN_FILE = Path("/sys/kernel/config/usb_gadget/contar/functions/mass_storage.0/lun.0/file")
USB_ADDRESS = "10.55.0.1"

_lock = threading.Lock()
_transfer = False
_simulated = os.environ.get("CONTAR_USB_SIMU", "") == "1"
_busy = False                 # rangement du dépôt en cours
_last_result: Optional[dict] = None
_last_result_at = 0.0
_undervoltage = False
_thread: Optional[threading.Thread] = None


def is_transfer_mode() -> bool:
    return _transfer


def available() -> bool:
    return _simulated or (platform.system() == "Linux" and UDC_ROOT.is_dir() and any(UDC_ROOT.iterdir()))


def status() -> dict:
    """Pour l'administration (page Import)."""
    return {
        "available": available(),
        "connected": _transfer,
        "busy": _busy,
        "undervoltage": _undervoltage,
        "address": USB_ADDRESS,
        "last_result": _last_result if time.monotonic() - _last_result_at < 15 * 60 else None,
    }


def _helper(*args: str, timeout: float = 120) -> tuple[bool, str]:
    try:
        result = subprocess.run(["sudo", HELPER, *args], capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            print(f"[USB] {' '.join(args)} : {result.stderr.strip() or result.stdout.strip()}")
        return result.returncode == 0, result.stdout.strip()
    except Exception as exc:
        print(f"[USB] {' '.join(args)} : {exc}")
        return False, ""


def _port_state() -> str:
    if _simulated:
        return "configured"
    try:
        udc = next(UDC_ROOT.iterdir())
        return (udc / "state").read_text().strip()
    except (OSError, StopIteration):
        return "absent"


def _storage_attached() -> bool:
    try:
        return bool(LUN_FILE.read_text().strip())
    except OSError:
        return False


def _check_power() -> None:
    """Bit 0 de get_throttled : sous-tension en ce moment."""
    global _undervoltage
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5).stdout
        value = int(out.strip().split("=")[1], 16)
        now = bool(value & 0x1)
    except Exception:
        return
    if now and not _undervoltage:
        print("[USB] sous-tension : l'ordinateur ne fournit pas assez de courant à la boîte.")
    _undervoltage = now


def _enter_transfer() -> None:
    global _transfer
    _transfer = True
    print("[USB] boîte reliée à un ordinateur : mode transfert.")
    try:
        from app import tag_playback
        from app.player import player_controller
        player_controller.fade_pause()
        tag_playback.save_now()
    except Exception as exc:
        print(f"[USB] {exc}")
    from app import power_manager, sound_feedback
    power_manager.note_activity()
    sound_feedback.play_plug()


def _leave_transfer() -> None:
    global _transfer
    _transfer = False
    print("[USB] câble débranché : fin du mode transfert.")
    from app import power_manager
    power_manager.note_activity()


def _take_depot() -> None:
    """Reprend le dépôt, range son contenu, le vide, le rend à l'ordinateur."""
    global _busy, _last_result, _last_result_at
    from app import depot_import, sound_feedback
    _busy = True
    try:
        _helper("storage-detach")
        ok, mount_point = _helper("depot-mount")
        if not ok or not mount_point:
            return
        result = depot_import.import_from(Path(mount_point))
        _helper("depot-umount")
        if result["status"] == "ok":
            _helper("depot-reset")
            print(f"[USB] dépôt rangé : {result['added']} fichier(s) ajouté(s), {result['present']} déjà présent(s).")
            sound_feedback.play_done()
        elif result["status"] == "vide":
            pass
        else:
            # Pas assez de place, copie interrompue : on garde le disque tel
            # quel, le parent verra le message dans l'administration.
            print(f"[USB] dépôt non rangé ({result['status']}).")
            sound_feedback.play_error()
        if result["status"] != "vide":
            _last_result, _last_result_at = result, time.monotonic()
    finally:
        if _port_state() == "configured":
            _helper("storage-attach")
        _busy = False


def _loop() -> None:
    # La boîte est alimentée par ce même port : débrancher l'ordinateur la
    # coupe net, avant qu'elle ait pu ranger le dépôt. On le range donc au
    # démarrage suivant, s'il contient quelque chose.
    if not _simulated and _port_state() != "configured":
        try:
            _take_depot()
        except Exception as exc:
            print(f"[USB] {exc}")
    was_attached = None
    power_tick = 0
    while True:
        try:
            connected = _port_state() == "configured"
            if connected and not _transfer:
                _enter_transfer()
                was_attached = _storage_attached()
            elif not connected and _transfer:
                _leave_transfer()
                if not _simulated:
                    _take_depot()   # câble débranché sans éjecter : on range quand même
                was_attached = None
            elif connected and not _simulated:
                attached = _storage_attached()
                if was_attached and not attached and not _busy:
                    _take_depot()   # l'ordinateur a éjecté le disque
                    attached = _storage_attached()
                was_attached = attached
            if connected:
                power_tick += 1
                if power_tick % 5 == 1:
                    _check_power()
            else:
                power_tick = 0
        except Exception as exc:
            print(f"[USB] {exc}")
        time.sleep(POLL_SECONDS)


def start() -> None:
    global _thread
    if _thread is not None:
        return
    if not available():
        print("[i] Port USB-C en mode périphérique non disponible (normal sur PC).")
        return
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    print("Câble USB-C surveillé : reliez la boîte à un ordinateur pour la remplir et la régler.")
