"""
Petits sons de confirmation joués DIRECTEMENT par la boîte (pas dans le
navigateur du parent) :
- un carillon bref au démarrage, pour confirmer que la boîte est prête
  sans avoir à ouvrir l'interface web ;
- deux bips brefs quand un tag posé sur le lecteur n'est associé à
  aucune histoire/musique (voir app/nfc_controller.py).

Les deux fichiers (app/assets/sounds/*.wav) sont générés par synthèse
(sinusoïdes pures, voir l'historique du projet) plutôt que téléchargés —
cohérent avec le reste du projet, pensé pour fonctionner sans accès
Internet.

Utilise une instance VLC totalement SÉPARÉE de celle de PlayerController
(voir app/player.py) : ces sons ne doivent jamais interrompre ni modifier
l'état d'une histoire en cours de lecture — juste se superposer
brièvement dessus. Même sortie ALSA que le lecteur principal
("--aout=alsa", périphérique "default") : c'est app/audio_output.py qui
pointe ce périphérique vers la bonne carte (gpio/jack/hdmi1/hdmi2), ce
module n'a donc rien de spécifique à gérer à ce sujet.

Best-effort partout : un souci quelconque (pas de carte son, VLC
indisponible, fichier manquant...) ne doit jamais faire planter le reste
de l'appli — juste rester silencieux, avec un message en console.
"""

import platform
from pathlib import Path
from typing import Optional

SOUNDS_DIR = Path(__file__).parent / "assets" / "sounds"
STARTUP_SOUND = SOUNDS_DIR / "startup.wav"
ERROR_SOUND = SOUNDS_DIR / "error.wav"
BEEP_SOUND = SOUNDS_DIR / "beep.wav"    # bip court : clé reconnue, « reposez le tag »
DONE_SOUND = SOUNDS_DIR / "done.wav"    # carillon de fin d'import

_instance = None
_player = None


def _get_player():
    """Créé au tout premier appel seulement (pas à l'import) : si VLC
    posait un jour souci, ça ne doit gêner que ce module précis."""
    global _instance, _player
    if _player is None:
        import vlc

        vlc_args = ["--no-video"]
        if platform.system() == "Linux":
            vlc_args.append("--aout=alsa")
        _instance = vlc.Instance(*vlc_args)
        _player = _instance.media_player_new()
        _player.audio_set_volume(80)
    return _player


def _play(path: Path) -> None:
    if not path.exists():
        print(f"[son] fichier manquant : {path}")
        return
    try:
        player = _get_player()
        media = _instance.media_new(str(path))
        player.set_media(media)
        player.play()
    except Exception as exc:
        print(f"[son] lecture impossible ({path.name}) : {exc}")


def play_startup() -> None:
    """Boîte prête — à appeler une fois au tout début du démarrage réel
    (voir run_pi.py / run_pi_gamepad.py), jamais sur run.py
    (PC de développement)."""
    _play(STARTUP_SOUND)


def play_unknown_tag() -> None:
    """Tag posé mais non associé — voir app/nfc_controller.py."""
    _play(ERROR_SOUND)


# ---- Import par clé USB (v0.9, voir app/usb_import.py) ----------------------
# Les mêmes sons, quelle que soit la langue : aucune annonce parlée.

def play_beep() -> None:
    """Bip court : la boîte a compris (clé reconnue, tag maître posé)."""
    _play(BEEP_SOUND)


def play_error() -> None:
    """Double bip : refus (pas de clé, clé non reconnue, pas assez de place)."""
    _play(ERROR_SOUND)


def play_done() -> None:
    """Carillon : import terminé."""
    _play(DONE_SOUND)
