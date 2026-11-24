"""
Contrôle par tags NFC/RFID (v0.11) : le tag est la télécommande.

    poser le tag        -> son contenu joue (reprise où ce tag en était)
    le retirer          -> pause en douceur, avancement enregistré
    le reposer vite     -> remise à zéro, depuis le début (son « rembobinage »)

Le geste est décidé par app/tag_gesture.py, le contenu et l'avancement
par app/tag_playback.py, le matériel par app/tag_reader.py : ce module ne
fait que relier les trois, avec les cas particuliers de la boîte :

- capture : l'administration attend un tag à associer (Tags → Associer) ;
  le tag posé est alors capturé et ne lance rien ;
- mode transfert : la boîte est branchée sur un ordinateur (USB-C, voir
  app/usb_gadget.py) ; les tags ne lancent rien, sauf la capture ;
- tag inconnu, contenu supprimé, hors des horaires autorisés : double bip.

La présence d'un tag est transmise à app/power_manager.py, qui ne met
jamais la boîte en veille tant qu'un tag est posé.
"""

import threading
import time
from typing import Optional

from app import sound_feedback
from app import tag_playback
from app.settings import SettingsManager
from app.tag_gesture import PAUSE, RESTART, TagGesture
from app.tag_reader import ManualReader, TagReader
from app.tags import TagManager

# Durée max pendant laquelle une capture ("posez le tag à associer") reste
# armée sans qu'aucun tag ne soit posé, avant d'abandonner toute seule.
CAPTURE_TIMEOUT_SECONDS = 60.0

_settings = SettingsManager()
_tags = TagManager()
_gesture = TagGesture(
    window_seconds=_settings.get_tag_double_window,
    double_enabled=_settings.get_tag_double_enabled,
)

_lock = threading.Lock()
_capturing = False
_capture_deadline = 0.0
_captured_uid: Optional[str] = None
_reader: Optional[TagReader] = None
_last_uid: Optional[str] = None       # dernier tag posé, pour l'administration


def begin_capture() -> None:
    global _capturing, _capture_deadline, _captured_uid
    with _lock:
        _capturing = True
        _capture_deadline = time.monotonic() + CAPTURE_TIMEOUT_SECONDS
        _captured_uid = None


def cancel_capture() -> None:
    global _capturing
    with _lock:
        _capturing = False


def is_capturing() -> bool:
    with _lock:
        if _capturing and time.monotonic() > _capture_deadline:
            return False
        return _capturing


def take_captured() -> Optional[str]:
    """Consomme et renvoie le dernier UID capturé (None si aucun depuis
    le dernier appel, ou si la capture a expiré sans qu'un tag soit posé)."""
    global _captured_uid
    with _lock:
        uid, _captured_uid = _captured_uid, None
        return uid


def present_uid() -> Optional[str]:
    """Tag actuellement posé sur la boîte (None si aucun)."""
    return _gesture.present_uid


def _power(present: bool) -> None:
    try:
        from app import power_manager
        power_manager.set_tag_present(present)
    except Exception as exc:
        print(f"[NFC] {exc}")


def _in_transfer_mode() -> bool:
    try:
        from app import usb_gadget
        return usb_gadget.is_transfer_mode()
    except Exception:
        return False


def _on_present(uid: str) -> None:
    global _capturing, _captured_uid, _last_uid
    _power(True)
    _last_uid = uid
    with _lock:
        if _capturing and time.monotonic() <= _capture_deadline:
            _captured_uid = uid
            _capturing = False
            _gesture.on_present(uid)
            _gesture.forget()
            sound_feedback.play_beep()
            return
        _capturing = False

    action = _gesture.on_present(uid)

    if _in_transfer_mode():
        print(f"[NFC] tag {uid} posé pendant un transfert USB : ignoré.")
        sound_feedback.play_error()
        return

    association = _tags.get(uid)
    if association is None:
        print(f"[NFC] tag inconnu (UID {uid}) — associez-le depuis l'administration, page Tags.")
        sound_feedback.play_unknown_tag()
        return

    if not _settings.is_allowed_now():
        # Réglages → Horaires : ne bloque QUE le lancement par tag ; une
        # lecture déjà en cours n'est jamais coupée par ce mécanisme.
        print(f"[NFC] tag {uid} reconnu mais hors plage horaire autorisée — lecture bloquée.")
        sound_feedback.play_error()
        return

    from_start = action == RESTART
    if from_start:
        print(f"[NFC] tag {uid} reposé aussitôt : on reprend depuis le début.")
        sound_feedback.play_rewind()
        time.sleep(0.6)   # laisse entendre le son avant l'histoire

    if not tag_playback.start(uid, association, from_start=from_start):
        # Contenu supprimé depuis, ou liste vide.
        print(f"[NFC] tag {uid} reconnu mais son contenu n'existe plus (supprimé ? liste vide ?).")
        sound_feedback.play_unknown_tag()


def _on_absent(uid: str) -> None:
    action = _gesture.on_absent(uid)
    _power(False)
    if action == PAUSE:
        tag_playback.pause(uid)


def start(reader: TagReader) -> None:
    """Démarre l'écoute du lecteur (voir app/tag_reader.py::make_reader())."""
    global _reader
    _reader = reader
    reader.start(on_present=_on_present, on_absent=_on_absent)
    print("Contrôle NFC actif : posez un tag pour écouter, retirez-le pour mettre en pause.")


def simulated_reader() -> Optional[ManualReader]:
    """Le lecteur simulé, s'il est en service (CONTAR_NFC=simu)."""
    return _reader if isinstance(_reader, ManualReader) else None


def set_slow_polling(slow: bool) -> None:
    """Veille légère : le lecteur interroge moins souvent (moins de courant)."""
    if _reader is not None and hasattr(_reader, "poll_interval"):
        _reader.poll_interval = 0.3 if slow else 0.05
