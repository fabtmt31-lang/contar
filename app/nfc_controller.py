"""
Contrôle par tags NFC/RFID : poser un tag associé (voir app/tags.py) sur
le lecteur lance directement le livre ou l'album correspondant, sans
passer par l'interface web.

Ne connaît RIEN d'un lecteur matériel en particulier (voir
app/tag_reader.py pour ça) — start(reader) reçoit une instance de
TagReader déjà choisie par le point d'entrée (run.py utilise
PCSCReader pour tester sur PC, run_pi.py/run_pi_gamepad.py utilisent
PN532Reader, le lecteur définitif de la boîte). Ce découpage permet de
garder les deux lecteurs disponibles en parallèle sans dupliquer la
logique de capture/association/déclenchement ci-dessous.

On ne réagit qu'à l'ARRIVÉE d'un tag, jamais à sa présence continue — un
tag oublié sur le lecteur ne doit pas relancer la même histoire en
boucle (voir app/tag_reader.py pour comment chaque lecteur applique
cette règle). Le retrait du tag, lui, n'a AUCUN effet sur la lecture
(choix de conception assumé, voir discussion du projet) : une fois
lancée, la lecture continue normalement, pilotée par les
boutons/manette comme n'importe quelle autre lecture — retirer le tag
ne met pas en pause.

Ce module gère aussi la "capture" utilisée par l'interface web
(Réglages → Tags NFC, "Associer un nouveau tag") : le même principe que
app/controls/mapping.py pour la capture d'un bouton, mais appliqué à un
UID de tag plutôt qu'à un control_id.
"""

import threading
import time
from typing import Optional

from app.player import player_controller
from app import lcd_display
from app import sound_feedback
from app import usb_import
from app.settings import SettingsManager
from app.tag_reader import TagReader
from app.tags import TagManager

_settings_manager = SettingsManager()

# Durée max pendant laquelle une capture ("posez le tag à associer") reste
# armée sans qu'aucun tag ne soit posé, avant d'abandonner toute seule —
# même principe que CAPTURE_TIMEOUT_SECONDS dans app/controls/mapping.py,
# juste un peu plus long ici (poser un tag prend un peu plus de temps que
# d'appuyer sur un bouton).
CAPTURE_TIMEOUT_SECONDS = 60.0

_tag_manager = TagManager()

_lock = threading.Lock()
_capturing = False
_capture_deadline = 0.0
_captured_uid: Optional[str] = None


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


def _on_tag_seen(uid: str) -> None:
    global _capturing, _captured_uid
    lcd_display.mark_activity()
    with _lock:
        if _capturing and time.monotonic() <= _capture_deadline:
            _captured_uid = uid
            _capturing = False
            return
        _capturing = False

    # Tags maîtres de l'import par clé USB (v0.9) : ils ne lancent jamais
    # d'histoire, et fonctionnent à toute heure (les horaires autorisés ne
    # concernent que la lecture). Voir app/usb_import.py.
    role = _settings_manager.master_tag_role(uid)
    if role is not None:
        print(f"[NFC] tag maître « {role} » posé.")
        usb_import.on_master_tag(role)
        return

    if usb_import.is_busy():
        # Pendant un import, les tags d'histoire sont ignorés.
        lcd_display.show_message("lcd.import_busy_line1", "lcd.import_busy_line2")
        return
    # Un autre tag posé entre les deux poses de « Remplacer » annule la demande.
    usb_import.cancel_confirmation()

    association = _tag_manager.get(uid)
    if association is None:
        print(f"[NFC] tag inconnu (UID {uid}) — associez-le depuis Réglages → Tags NFC.")
        sound_feedback.play_unknown_tag()
        lcd_display.show_unknown_tag()
        return

    if not _settings_manager.is_allowed_now():
        # Réglages → Horaires (app/settings.py::is_allowed_now(), en place
        # depuis longtemps mais jamais exploité nulle part avant ce jour)
        # — ne bloque QUE le lancement d'une nouvelle histoire par tag ;
        # une lecture déjà en cours n'est jamais coupée par ce mécanisme.
        print(f"[NFC] tag reconnu (UID {uid}) mais hors plage horaire autorisée — lecture bloquée.")
        lcd_display.show_quiet_hours()
        return

    if association["kind"] == "book":
        started = player_controller.play("book", association["item_id"])
    else:
        started = player_controller.play_album(association["item_id"])

    if not started:
        # Le livre/album associé à ce tag a été supprimé depuis (voir
        # app/library_delete.py) — sans cette vérification, l'écran
        # affichait "Tag reconnu" avec le titre de la lecture PRÉCÉDENTE
        # (celui encore en mémoire dans player.py), ce qui est faux et
        # trompeur pour l'enfant.
        print(f"[NFC] tag reconnu (UID {uid}) mais son contenu associé n'existe plus (supprimé ?).")
        sound_feedback.play_unknown_tag()
        lcd_display.show_unknown_tag()
        return

    # Titre déjà résolu par player.py (voir get_state()) — pas de requête
    # supplémentaire nécessaire ici pour l'affichage écran.
    title = player_controller.get_state().get("title") or ""
    lcd_display.show_tag_scanned(title)


def start(reader: TagReader) -> None:
    """
    Démarre l'écoute du lecteur — voir app/tag_reader.py pour les
    implémentations disponibles (PCSCReader, PN532Reader) et
    app/run_pi.py/run.py/etc. pour lequel est injecté selon la cible.
    """
    reader.start(on_tag_seen=_on_tag_seen)
    print("Contrôle NFC actif : posez un tag associé pour lancer une histoire (Réglages → Tags NFC).")
