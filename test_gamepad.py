"""
Calibration de la manette USB : affiche en direct chaque appui / mouvement
détecté, avec le code exact envoyé par VOTRE manette.

À lancer sur la machine où la manette est branchée (PC de test ou la
future "boîte") :

    python test_gamepad.py

Appuyez sur chaque bouton et poussez la croix dans les 4 directions : une
ligne s'affiche à chaque fois.

Pour un bouton "INCONNU" (jamais vu, aucune action assignée) : plus besoin
de modifier du code — ouvrez l'interface web, "Réglages → Boutons /
manette", et utilisez "Ajouter un bouton" sur l'action voulue : appuyez
sur ce bouton, il sera capturé et assigné automatiquement (voir
app/controls/mapping.py). Ce script reste utile pour comprendre pourquoi
un bouton ne répond pas (mauvais type d'événement, croix envoyée comme
axe non reconnu, etc.) — dans ce cas précis (axe absent de
RECOGNIZED_AXIS_CODES dans app/controls/gamepad_controller.py), c'est le
seul cas où il faut encore éditer ce fichier à la main.

Ctrl+C pour quitter.
"""

from app.controls import mapping
from app.controls.gamepad_controller import RECOGNIZED_AXIS_CODES

try:
    from inputs import get_gamepad, UnpluggedError
except ImportError:
    raise SystemExit("Installez d'abord la dépendance : pip install inputs")

print("En attente d'une manette USB... (Ctrl+C pour quitter)\n")

while True:
    try:
        events = get_gamepad()
    except UnpluggedError:
        print("Aucune manette détectée pour l'instant, branchez-la...")
        continue
    except KeyboardInterrupt:
        break

    for event in events:
        if event.ev_type not in ("Key", "Absolute"):
            continue  # ignore la synchronisation interne, pas utile ici

        known = (
            event.code in mapping.get_mapping("gamepad")["bindings"]
            if event.ev_type == "Key"
            else event.code in RECOGNIZED_AXIS_CODES
        )
        status = "connu (déjà mappé)" if known else "INCONNU — à ajouter si besoin"

        print(
            f"type={event.ev_type:<9} code={event.code:<18} "
            f"valeur={event.state:<5} [{status}]"
        )
