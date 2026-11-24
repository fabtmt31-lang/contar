"""
Contrôle par 5 boutons physiques câblés sur les GPIO du Raspberry Pi.

Ce module ne s'importe/s'exécute que sur le Pi lui-même (gpiozero a
besoin d'un vrai GPIO ou d'une bibliothèque système comme lgpio) — pas
testable sur PC, contrairement à keyboard_controller.py qui le remplace
pendant le développement.

Câblage attendu (le plus simple, sans composant supplémentaire) : chaque
bouton relie le GPIO choisi à une broche GND. pull_up=True active la
résistance de tirage interne du Pi, donc pas de résistance externe
nécessaire.

Numérotation BCM ci-dessous : c'est le câblage physique, fixe (5 boutons
soudés/câblés sur ces broches précises). Ce qui EST réglable, en
revanche, c'est quelle ACTION chaque bouton déclenche, et lesquels deux
boutons maintenus ensemble éteignent la boîte — voir
app/controls/mapping.py et "Réglages → Boutons / manette" dans
l'interface web.
"""

from app.controls import mapping
from app.controls.actions import trigger

MODE = "gpio"

# Câblage physique fixe (broches BCM) — à ajuster ici une seule fois si
# besoin, une fois la boîte câblée différemment. Les ACTIONS associées à
# chaque broche, elles, se réglent depuis l'interface web, pas ici.
#
# v0.10.1 : le bouton de la broche 19 passe sur la broche 16. L'ampli
# MAX98357A (son par les broches, en I2S) occupe les broches 18, 19 et 21 :
# un bouton ne peut plus s'y trouver. La 16 est sa voisine sur le
# connecteur (broche physique 36, juste en face de la 35) : un seul fil à
# déplacer d'un cran. Les réglages déjà faits suivent (_migrate_moved_pins).
#
# v0.10.3 : la liste suit le schéma de câblage de la boîte (cahier des
# charges, « Câblage ») — retour GPIO 17, lecture/pause GPIO 27, avance
# GPIO 22, volume − GPIO 5, volume + GPIO 6, masse commune en broche 25.
# Les broches 13, 16 et 26 des versions précédentes restent écoutées : un
# bouton qui y serait encore branché continue de fonctionner. Le rôle de
# chaque bouton se règle dans Réglages → Boutons, par « Ajouter un bouton ».
PINS = [17, 27, 22, 5, 6, 13, 16, 26]
MOVED_PINS = {"19": "16"}     # ancienne broche -> nouvelle

BOUNCE_TIME_SECONDS = 0.05  # anti-rebond, évite qu'un seul appui déclenche deux fois

_buttons = []  # référence conservée pour que les boutons ne soient pas nettoyés par le ramasse-miettes


def _on_control_pressed(control_id: str) -> None:
    if mapping.offer_capture(control_id):
        return
    mapping.notify_press(control_id)
    action = mapping.get_mapping(MODE)["bindings"].get(control_id)
    if action:
        trigger(action)


def _on_control_released(control_id: str) -> None:
    mapping.notify_release(control_id)


def _migrate_moved_pins() -> None:
    """Reporte sur la nouvelle broche l'action (et le rôle dans la
    combinaison d'extinction) réglés pour un bouton qui a changé de broche."""
    from app.settings import SettingsManager

    settings = SettingsManager()
    stored = settings.get_control_mapping(MODE)
    if not stored:
        return
    bindings = dict(stored.get("bindings") or {})
    combo = list(stored.get("shutdown_combo") or ["", ""])
    changed = False
    for old, new in MOVED_PINS.items():
        if old in bindings:
            action = bindings.pop(old)
            bindings.setdefault(new, action)
            changed = True
        if old in combo:
            combo = [new if code == old else code for code in combo]
            changed = True
    if changed:
        settings.set_control_mapping(MODE, {**stored, "bindings": bindings, "shutdown_combo": combo})
        mapping.reload(MODE)
        print(f"[boutons] réglages reportés sur les nouvelles broches : {MOVED_PINS}.")


def start() -> None:
    from gpiozero import Button

    try:
        _migrate_moved_pins()
    except Exception as exc:
        print(f"[boutons] report des réglages impossible : {exc}")

    mapping.set_active_mode(MODE)
    mapping.ensure_watcher_started()

    ready = 0
    for pin in PINS:
        control_id = str(pin)
        try:
            button = Button(pin, pull_up=True, bounce_time=BOUNCE_TIME_SECONDS)
        except Exception as exc:
            # Broche déjà prise par autre chose (ampli, écran…) : ce bouton
            # est ignoré, la boîte démarre quand même. Avant la v0.10.1,
            # une seule broche occupée empêchait tout le programme de partir.
            print(f"[boutons] broche GPIO {pin} indisponible ({exc}) : bouton ignoré.")
            continue
        button.when_pressed = lambda control_id=control_id: _on_control_pressed(control_id)
        button.when_released = lambda control_id=control_id: _on_control_released(control_id)
        _buttons.append(button)
        ready += 1

    print(
        f"Contrôle GPIO actif : {ready} bouton(s) physique(s) prêt(s) sur {len(PINS)} — réglables "
        "depuis Réglages → Boutons / manette."
    )
    # Les callbacks gpiozero tournent sur un thread interne à la librairie :
    # rien à bloquer ici, start() peut être appelé sans arrêter le programme.
