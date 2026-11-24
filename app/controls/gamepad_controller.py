"""
Contrôle par manette USB façon NES — pour la "boîte" (PC x86 en mode
kiosque) et pour le Raspberry Pi sans câblage GPIO, remplace à la fois
keyboard_controller.py (PC de dev) et gpio_controller.py.

Quel bouton déclenche quelle action (et quels deux boutons maintenus
ensemble éteignent la boîte) n'est PAS codé en dur ici : c'est
app/controls/mapping.py qui porte ce mapping, réglable depuis
l'interface web ("Réglages → Boutons / manette"). Ce module ne fait que
lire les événements bruts de la manette et les transmettre à mapping.py.

Nécessite la librairie "inputs" (pip install inputs), pure Python, sans
dépendance système (contrairement à pygame qui a besoin de SDL). Elle lit
directement les périphériques /dev/input/event* : l'utilisateur qui lance
le programme doit appartenir au groupe "input" (voir install_pi.sh, qui
s'en charge automatiquement).

Important : les clones USB de manette NES ne sont pas tous identiques —
certains envoient la croix directionnelle comme un "hat" (ABS_HAT0X/Y),
d'autres comme des axes classiques (ABS_X/Y), d'autres encore comme de
simples boutons numérotés. Le réglage d'usine (mapping.DEFAULT_GAMEPAD_*)
couvre les cas les plus courants ; si un bouton de votre manette n'est
reconnu par rien, utilisez "Réglages → Boutons / manette → Réassigner" :
appuyez dessus, il sera capturé quel que soit son code exact. Pour du
diagnostic plus poussé, `python test_gamepad.py` à la racine du projet
affiche les codes bruts envoyés.
"""

import threading
import time

from app.controls import mapping
from app.controls.actions import trigger

MODE = "gamepad"

# Codes d'axes/hat reconnus par défaut : ceux d'une croix directionnelle
# (hat) ou d'un stick analogique utilisé comme croix. Certaines manettes
# envoient leur croix sur un tout autre axe (ex: ABS_RX, ABS_RZ) : plutôt
# que de faire échouer la capture "appuyez sur le bouton" pour ces
# clones, TOUT axe est écouté pendant une capture (voir _handle_event) —
# une fois un axe capturé et assigné à une action, il apparaît dans les
# bindings et devient reconnu en dispatch normal aussi (voir
# _recognized_axis_codes ci-dessous), sans qu'il faille éditer ce fichier.
RECOGNIZED_AXIS_CODES = {"ABS_HAT0X", "ABS_HAT0Y", "ABS_X", "ABS_Y"}


def _recognized_axis_codes() -> set[str]:
    codes = set(RECOGNIZED_AXIS_CODES)
    for key in mapping.get_mapping(MODE)["bindings"]:
        if key.startswith("AXIS:"):
            codes.add(key.split(":")[1])
    return codes

# Certaines manettes envoient des valeurs brutes (0-255) plutôt que -1/0/1
# sur les axes classiques (ABS_X/ABS_Y) : on normalise avec un seuil.
AXIS_LOW_THRESHOLD = 96
AXIS_HIGH_THRESHOLD = 160

# Codes de "hat switch" au sens strict du noyau Linux : sur CES codes
# précis, evdev ne renvoie JAMAIS autre chose que -1/0/1 (jamais de
# valeur intermédiaire) — la valeur brute est donc directement la
# direction. Sur tout autre code d'axe (ABS_X/Y, ABS_RX...), utilisé par
# certains clones pour simuler la croix directionnelle, la plage brute
# est plutôt 0-255 centrée sur ~128 (voir AXIS_LOW/HIGH_THRESHOLD).
_HAT_AXIS_CODES = {"ABS_HAT0X", "ABS_HAT0Y", "ABS_HAT1X", "ABS_HAT1Y", "ABS_HAT2X", "ABS_HAT2Y"}

_last_axis_state: dict[str, int] = {}
_stop_flag = threading.Event()
_thread: threading.Thread | None = None


def _normalize_axis_value(code: str, raw: int) -> int:
    """
    Ramène une valeur d'axe brute à -1 / 0 / 1.

    Bug corrigé (retour de test réel) : un raccourci global traitait
    toute valeur brute déjà dans {-1, 0, 1} comme la direction finale,
    quel que soit le code. Ça casse les clones qui simulent la croix
    directionnelle sur un axe générique (ABS_X/Y...) avec une plage 0-255 :
    leur extrémité "gauche"/"haut" vaut exactement 0, qui se retrouvait
    alors interprété comme "relâché" au lieu de "poussé à fond côté bas"
    — d'où gauche/haut jamais détectés alors que droite/bas (valeur haute,
    255) fonctionnaient. La distinction se fait maintenant par code : les
    vrais codes de hat (ABS_HAT0X/Y...) restent pris tels quels (le noyau
    ne renvoie jamais autre chose que -1/0/1 dessus), tout le reste passe
    systématiquement par le seuillage.
    """
    if code in _HAT_AXIS_CODES:
        if raw in (-1, 0, 1):
            return raw
        return 1 if raw > 0 else -1
    if raw <= AXIS_LOW_THRESHOLD:
        return -1
    if raw >= AXIS_HIGH_THRESHOLD:
        return 1
    return 0


def _on_control_pressed(control_id: str) -> None:
    if mapping.offer_capture(control_id):
        # Bouton "avalé" par une capture en cours côté réglages web :
        # pas d'action déclenchée, juste rapporté à mapping.py.
        return
    mapping.notify_press(control_id)
    action = mapping.get_mapping(MODE)["bindings"].get(control_id)
    if action:
        trigger(action)


def _on_control_released(control_id: str) -> None:
    mapping.notify_release(control_id)


def _handle_event(event) -> None:
    code = event.code

    if event.ev_type == "Key":
        if event.state == 1:  # 1 = appui, 0 = relâchement
            _on_control_pressed(code)
        elif event.state == 0:
            _on_control_released(code)
        return

    if event.ev_type == "Absolute" and (mapping.is_capturing() or code in _recognized_axis_codes()):
        value = _normalize_axis_value(code, event.state)
        previous = _last_axis_state.get(code, 0)
        if value == previous:
            return
        _last_axis_state[code] = value
        if previous != 0:
            _on_control_released(f"AXIS:{code}:{previous}")
        if value != 0:
            _on_control_pressed(f"AXIS:{code}:{value}")


def _listen_loop() -> None:
    from inputs import get_gamepad, UnpluggedError

    print("[gamepad] En attente d'une manette USB...")
    warned_once = False

    while not _stop_flag.is_set():
        try:
            events = get_gamepad()
        except UnpluggedError:
            if not warned_once:
                print(
                    "[gamepad] Aucune manette détectée. Branchez-la : "
                    "elle sera prise en compte automatiquement (aucun "
                    "redémarrage nécessaire)."
                )
                warned_once = True
            time.sleep(1)
            continue
        except Exception as exc:  # défensif : ne jamais planter le programme principal
            print(f"[gamepad] Erreur de lecture ({exc}), nouvelle tentative...")
            time.sleep(1)
            continue

        warned_once = False
        for event in events:
            _handle_event(event)


def start() -> None:
    """Démarre l'écoute de la manette dans un thread d'arrière-plan (non bloquant)."""
    global _thread
    mapping.set_active_mode(MODE)
    mapping.ensure_watcher_started()
    _thread = threading.Thread(target=_listen_loop, daemon=True)
    _thread.start()
    print(
        "Contrôle manette actif : croix = avance/recul (gauche/droite) et "
        "volume (haut/bas), A/B = lecture/pause par défaut — réglable "
        "depuis Réglages → Boutons / manette."
    )
