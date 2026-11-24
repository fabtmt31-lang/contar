"""
Configuration des boutons physiques (manette USB ou boutons GPIO) :
quelle action chaque bouton déclenche, et quels DEUX boutons doivent être
maintenus enfoncés ensemble pour éteindre la boîte.

Point important de sécurité enfant, voulu explicitement : l'extinction
n'est JAMAIS assignable à un simple appui sur un seul bouton — uniquement
à un appui SIMULTANÉ MAINTENU sur deux boutons distincts (HOLD_SECONDS),
pour qu'un enfant ne puisse pas l'éteindre par erreur en jouant avec un
seul bouton. Ce n'est pas un réglage désactivable depuis l'interface :
seuls LES DEUX BOUTONS de la combinaison sont reconfigurables, pas le
principe lui-même.

Ce module est commun aux deux contrôleurs physiques
(gamepad_controller.py / gpio_controller.py) : chacun lui délègue tout ce
qui concerne "quel bouton fait quoi", et se contente de lui signaler ses
appuis/relâchements bruts via notify_press()/notify_release() (et
offer_capture() pour la capture "appuyez sur le bouton à assigner" côté
interface web). Le clavier PC (keyboard_controller.py) n'est PAS
concerné : son mapping reste fixe, c'est un outil de développement, pas
un vrai boîtier avec un enfant en face.

Un "control_id" est un identifiant de bouton physique sous forme de
chaîne, propre à chaque mode :
- manette ("gamepad") : le code brut envoyé par la lib "inputs"
  (ex: "BTN_SOUTH"), ou pour les axes/croix directionnelle,
  "AXIS:<code>:<direction>" (ex: "AXIS:ABS_HAT0X:-1")
- GPIO ("gpio") : le numéro de broche BCM, en texte (ex: "5")
"""

import threading
import time
from typing import Optional

from app.settings import SettingsManager

# Les actions qu'un parent peut réassigner à un bouton. L'extinction
# n'apparaît volontairement PAS ici : voir le docstring du module.
ASSIGNABLE_ACTIONS = [
    "play_pause", "seek_back", "seek_forward",
    "prev_track", "next_track",
    "volume_up", "volume_down",
    "resume",
]

ACTION_LABELS = {
    "play_pause": "Lecture / Pause",
    "seek_back": "Retour 10 s",
    "seek_forward": "Avance 10 s",
    "prev_track": "Piste précédente",
    "next_track": "Piste suivante",
    "volume_up": "Volume +",
    "volume_down": "Volume -",
    "resume": "Reprendre la dernière lecture",
}

# ---- Réglages d'usine ----------------------------------------------------
#
# Aucun bouton n'est assigné par défaut (ni combinaison d'extinction) :
# chaque manette/boîtier envoie des codes différents, un mapping
# préréglé se révélait plus souvent source de confusion (boutons qui
# "font déjà quelque chose" sans qu'on sache pourquoi) qu'utile. Le
# parent assigne chaque bouton lui-même via "Ajouter un bouton" (capture),
# voir "Réglages → Boutons / manette" — quelques secondes par bouton.
DEFAULT_GAMEPAD_BINDINGS: dict[str, str] = {}
DEFAULT_GAMEPAD_SHUTDOWN_COMBO = ["", ""]

DEFAULT_GPIO_BINDINGS: dict[str, str] = {}
DEFAULT_GPIO_SHUTDOWN_COMBO = ["", ""]

# Durée d'appui simultané requise avant extinction.
HOLD_SECONDS = 2.0
# Durée max pendant laquelle une capture ("appuyez sur le bouton...")
# reste armée sans appui, avant d'abandonner toute seule (sécurité : évite
# qu'un onglet de réglages oublié ouvert avale le prochain appui, des
# heures plus tard).
CAPTURE_TIMEOUT_SECONDS = 30.0


def _defaults(mode: str) -> dict:
    if mode == "gpio":
        return {"bindings": dict(DEFAULT_GPIO_BINDINGS), "shutdown_combo": list(DEFAULT_GPIO_SHUTDOWN_COMBO)}
    return {"bindings": dict(DEFAULT_GAMEPAD_BINDINGS), "shutdown_combo": list(DEFAULT_GAMEPAD_SHUTDOWN_COMBO)}


_lock = threading.Lock()
_cache: dict[str, dict] = {}


def _load(mode: str) -> None:
    stored = SettingsManager().get_control_mapping(mode)
    _cache[mode] = stored if stored else _defaults(mode)


def get_mapping(mode: str) -> dict:
    """{"bindings": {control_id: action}, "shutdown_combo": [control_id, control_id]}"""
    with _lock:
        if mode not in _cache:
            _load(mode)
        return _cache[mode]


def reload(mode: str) -> None:
    """Recharge depuis la base — utile si le mapping a été modifié par un
    autre processus (pas le cas normalement, tout tourne dans le même
    processus Flask, mais reste bon marché et prudent)."""
    with _lock:
        _load(mode)


def controls_for_action(mode: str, action: str) -> list[str]:
    bindings = get_mapping(mode)["bindings"]
    return sorted(code for code, a in bindings.items() if a == action)


def add_binding(mode: str, action: str, control_id: str) -> None:
    """Assigne ce bouton à cette action. Un bouton n'appartient qu'à une
    seule action à la fois : s'il était déjà utilisé ailleurs, il en est
    retiré automatiquement."""
    with _lock:
        if mode not in _cache:
            _load(mode)
        data = _cache[mode]
        bindings = dict(data["bindings"])
        bindings[control_id] = action
        data = {**data, "bindings": bindings}
        _cache[mode] = data
        SettingsManager().set_control_mapping(mode, data)


def remove_binding(mode: str, action: str, control_id: str) -> tuple[bool, str]:
    """Retire ce bouton de cette action. Refuse de vider complètement une
    action (il doit toujours rester au moins un bouton qui la déclenche)."""
    with _lock:
        if mode not in _cache:
            _load(mode)
        data = _cache[mode]
        bindings = dict(data["bindings"])
        if bindings.get(control_id) != action:
            return False, "Ce bouton n'est plus assigné à cette action."
        remaining = sum(1 for a in bindings.values() if a == action) - 1
        if remaining < 1:
            return False, "Il doit rester au moins un bouton pour cette action."
        del bindings[control_id]
        data = {**data, "bindings": bindings}
        _cache[mode] = data
        SettingsManager().set_control_mapping(mode, data)
        return True, "Bouton retiré."


def set_shutdown_combo_slot(mode: str, slot: int, control_id: str) -> tuple[bool, str]:
    """slot vaut 0 ou 1 (premier ou second bouton de la combinaison)."""
    with _lock:
        if mode not in _cache:
            _load(mode)
        data = _cache[mode]
        combo = list(data.get("shutdown_combo") or _defaults(mode)["shutdown_combo"])
        other = combo[1 - slot]
        if control_id == other:
            return False, "Les deux boutons de l'extinction doivent être différents."
        combo[slot] = control_id
        data = {**data, "shutdown_combo": combo}
        _cache[mode] = data
        SettingsManager().set_control_mapping(mode, data)
        return True, "Combinaison d'extinction mise à jour."


def reset_to_default(mode: str) -> None:
    with _lock:
        defaults = _defaults(mode)
        _cache[mode] = defaults
        SettingsManager().set_control_mapping(mode, defaults)


# ---- Capture : "appuyez sur le bouton à assigner" (utilisé par l'interface web) ----
#
# Le contrôleur (gamepad_controller / gpio_controller) appelle
# offer_capture(control_id) à CHAQUE appui détecté, avant de faire quoi
# que ce soit d'autre : si une capture est armée, l'appui est "avalé"
# (mémorisé pour l'interface web, qui le récupère via take_captured()) et
# ne déclenche PAS l'action normalement associée à ce bouton — évite
# qu'appuyer sur le bouton à réassigner fasse aussi, par exemple, sauter
# le morceau en cours.

_capturing = False
_capture_deadline = 0.0
_captured_code: Optional[str] = None


def begin_capture() -> None:
    global _capturing, _capture_deadline, _captured_code
    with _lock:
        _capturing = True
        _capture_deadline = time.monotonic() + CAPTURE_TIMEOUT_SECONDS
        _captured_code = None


def cancel_capture() -> None:
    global _capturing
    with _lock:
        _capturing = False


def is_capturing() -> bool:
    with _lock:
        if _capturing and time.monotonic() > _capture_deadline:
            return False
        return _capturing


def offer_capture(control_id: str) -> bool:
    """Renvoie True si l'appui a été consommé par une capture en cours —
    l'appelant ne doit alors PAS déclencher l'action normale du bouton."""
    global _capturing, _captured_code
    with _lock:
        if not _capturing or time.monotonic() > _capture_deadline:
            _capturing = False
            return False
        _captured_code = control_id
        _capturing = False
        return True


def take_captured() -> Optional[str]:
    """Consomme et renvoie le dernier bouton capturé (None si aucun
    depuis le dernier appel, ou si la capture a expiré sans appui)."""
    global _captured_code
    with _lock:
        code, _captured_code = _captured_code, None
        return code


# ---- Détection de l'appui simultané maintenu (extinction) ---------------

_current_mode: Optional[str] = None
_held_since: dict[str, float] = {}
_combo_fired = False
_watcher_started = False


def notify_press(control_id: str) -> None:
    with _lock:
        _held_since.setdefault(control_id, time.monotonic())


def notify_release(control_id: str) -> None:
    global _combo_fired
    with _lock:
        _held_since.pop(control_id, None)
        _combo_fired = False


def _combo_watch_loop() -> None:
    global _combo_fired
    from app.controls.actions import trigger

    while True:
        time.sleep(0.15)
        mode = _current_mode
        if mode is None:
            continue

        combo = get_mapping(mode).get("shutdown_combo") or []
        if len(combo) != 2:
            continue

        with _lock:
            if _combo_fired:
                continue
            now = time.monotonic()
            both_held_long_enough = all(
                code in _held_since and (now - _held_since[code]) >= HOLD_SECONDS
                for code in combo
            )
            if both_held_long_enough:
                _combo_fired = True

        if both_held_long_enough:
            print("[manette/GPIO] Combinaison d'extinction détectée (appui simultané maintenu).")
            trigger("shutdown")


def set_active_mode(mode: str) -> None:
    """Appelé par le contrôleur qui démarre réellement (gamepad ou GPIO),
    pour que la boucle de détection de la combinaison d'extinction sache
    quel plan de boutons surveiller, et pour que la page de réglages
    sache quel mode est actif sur cette installation."""
    global _current_mode
    _current_mode = mode
    SettingsManager().set_control_mode(mode)


def ensure_watcher_started() -> None:
    global _watcher_started
    with _lock:
        if _watcher_started:
            return
        _watcher_started = True
    thread = threading.Thread(target=_combo_watch_loop, daemon=True)
    thread.start()
