"""
Contrôle clavier — pour tester les 5 boutons physiques directement sur
PC, sans matériel GPIO. Correspondance :

    Espace         -> lecture / pause
    Flèche gauche  -> retour de 10 secondes
    Flèche droite  -> avance de 10 secondes
    Flèche haut    -> volume +
    Flèche bas     -> volume -

Nécessite la librairie "keyboard" (pip install keyboard). L'écoute est
globale : les touches fonctionnent même si le navigateur a le focus,
exactement comme des boutons physiques indépendants de l'écran.

Sous Linux/Mac, une élévation de droits (sudo) peut être nécessaire pour
l'écoute clavier globale — sans objet une fois sur le vrai Raspberry Pi,
qui utilisera le contrôle GPIO (voir gpio_controller.py) et non celui-ci.
"""

import keyboard

from app.controls.actions import trigger

KEY_BINDINGS = {
    "space": "play_pause",
    "left": "seek_back",
    "right": "seek_forward",
    "up": "volume_up",
    "down": "volume_down",
}


def start() -> None:
    """Enregistre les raccourcis clavier. Ne bloque pas : l'écoute tourne en arrière-plan."""
    for key, action in KEY_BINDINGS.items():
        keyboard.add_hotkey(key, trigger, args=(action,))
    print(
        "Contrôle clavier actif : Espace = lecture/pause, "
        "←/→ = retour/avance 10s, ↑/↓ = volume."
    )
