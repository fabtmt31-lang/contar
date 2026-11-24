"""
Petite fonction partagée pour éteindre le Raspberry Pi — utilisée à la
fois par le bouton "Éteindre" de l'interface web (app/web/routes.py) et
par la combinaison de boutons physiques maintenus ensemble (voir
app/controls/mapping.py), pour ne jamais dupliquer la logique
(vérification de plateforme + appel système) à deux endroits différents.
"""

import platform
import subprocess


def shutdown_now() -> tuple[bool, str]:
    """
    Tente d'éteindre proprement. Ne fait rien de destructif hors Linux
    (PC de développement Windows/Mac) : renvoie juste un message
    explicatif. Le "sudo shutdown" fonctionne sans mot de passe sur le Pi
    grâce à la règle sudoers dédiée posée par install_pi.sh.
    """
    if platform.system() != "Linux":
        return False, "L'extinction n'est disponible que sur le vrai Raspberry Pi, pas pendant les tests sur PC."
    try:
        subprocess.Popen(["sudo", "shutdown", "-h", "now"])
        return True, "Extinction en cours..."
    except Exception as exc:
        return False, f"Impossible d'éteindre : {exc}"


def reboot_now() -> tuple[bool, str]:
    """
    Redémarre le Pi (utilisé par "Réinitialisation usine", voir
    app/factory_reset.py, pour repartir sur une boîte fraîchement remise
    à zéro). Même binaire que shutdown_now() ci-dessus ("shutdown", juste
    avec "-r" au lieu de "-h") : la règle sudoers posée par install_pi.sh
    pour le bouton "Éteindre" autorise ce binaire SANS restreindre ses
    arguments (`NOPASSWD: /sbin/shutdown`, pas
    `NOPASSWD: /sbin/shutdown -h now`) — donc "-r now" est déjà couvert,
    pas besoin d'une règle sudoers séparée.
    """
    if platform.system() != "Linux":
        return False, "Le redémarrage n'est disponible que sur le vrai Raspberry Pi, pas pendant les tests sur PC."
    try:
        subprocess.Popen(["sudo", "shutdown", "-r", "now"])
        return True, "Redémarrage en cours..."
    except Exception as exc:
        return False, f"Impossible de redémarrer : {exc}"
