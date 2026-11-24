"""
Point d'entrée central pour les actions physiques : peu importe la source
(boutons GPIO sur le Pi, clavier sur PC, manette USB), chaque source
appelle uniquement trigger(action) — jamais directement player_controller
ni un appel système. Ça garantit un comportement identique partout et un
seul endroit à modifier si la logique doit changer.

"shutdown" est un cas à part : ce n'est JAMAIS un bouton unique assignable
librement (voir app/controls/mapping.py) — uniquement la combinaison de
deux boutons maintenus ensemble, détectée par ce même module.
"""

from app.player import player_controller
from app.system_control import shutdown_now
from app import lcd_display

ACTIONS = {
    "play_pause": lambda: player_controller.toggle_play_pause(),
    "seek_back": lambda: player_controller.skip_back(),
    "seek_forward": lambda: player_controller.skip_forward(),
    "prev_track": lambda: player_controller.previous_track(),
    "next_track": lambda: player_controller.next_track(),
    "volume_up": lambda: _adjust_volume(player_controller.volume_up),
    "volume_down": lambda: _adjust_volume(player_controller.volume_down),
    "resume": lambda: _resume_last_played(),
    "shutdown": lambda: shutdown_now(),
}


def _adjust_volume(adjust_fn) -> None:
    """Ajuste le volume puis affiche brièvement le nouveau niveau sur
    l'écran (voir app/lcd_display.py::show_volume())."""
    adjust_fn()
    lcd_display.show_volume(player_controller.get_state()["volume"])


def _resume_last_played() -> None:
    """
    Action "Reprendre" (étape 32) : relance la dernière lecture en cours
    (livre ou morceau) à l'endroit exact où elle s'était arrêtée — sans
    passer par un tag NFC, pour le cas où l'enfant redémarre la boîte et
    veut juste continuer sans redemander au parent de reposer le tag.
    play() reprend déjà la position sauvegardée tout seul (voir
    app/player.py) ; s'il n'existe encore aucune lecture antérieure
    (toute première utilisation), ne fait simplement rien.
    """
    last = player_controller.get_last_played()
    if last is not None:
        player_controller.play(last["kind"], last["item_id"])


def trigger(action: str) -> None:
    lcd_display.mark_activity()
    handler = ACTIONS.get(action)
    if handler is None:
        raise ValueError(f"Action de contrôle inconnue : {action!r}")
    handler()
