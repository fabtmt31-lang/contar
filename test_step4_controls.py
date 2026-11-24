"""
Vérifie le contrôle clavier indépendamment du navigateur : démarre
l'écoute clavier puis affiche l'état du lecteur toutes les 2 secondes,
pour voir vos appuis agir en direct sans même ouvrir de page web.

Touches : Espace = lecture/pause, ←/→ = retour/avance 10s, ↑/↓ = volume.
Ctrl+C pour arrêter.

Assurez-vous d'avoir déjà une histoire chargée avant de tester (ex :
lancez test_step2.py dans un autre terminal et faites 'play book 1',
ou lancez run.py et démarrez une lecture depuis l'interface web).
"""

import time

from app.controls.keyboard_controller import start as start_keyboard_controls
from app.player import player_controller


def main() -> None:
    start_keyboard_controls()
    print("Ctrl+C pour arrêter.\n")
    try:
        while True:
            state = player_controller.get_state()
            if state["kind"] is None:
                print("(rien en cours — lancez une lecture via test_step2.py ou l'interface web)")
            else:
                status = "lecture" if state["is_playing"] else "pause"
                print(
                    f"[{status}] {state['title']} | "
                    f"{state['position_ms'] // 1000}s | volume {state['volume']}%"
                )
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    main()
