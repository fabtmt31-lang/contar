"""
Point d'accès Wifi de secours ("Wifi Direct") : si la boîte n'arrive pas à
se connecter au Wifi de la maison (jamais configuré, mot de passe
changé/faux, borne hors de portée...), elle crée automatiquement son
propre réseau Wifi le temps d'être reconfigurée — plus besoin d'un écran
ni d'un câble Ethernet pour la déboguer.

Ce module ne fait QUE lire l'état et écrire la configuration (activé,
SSID, mot de passe) dans un fichier miroir en texte brut. La bascule
elle-même (créer/couper le point d'accès via NetworkManager) est gérée
par un script système indépendant qui tourne en continu, EN ROOT, via son
propre service systemd (bin/wifi-fallback-watchdog.sh, installé par
install_pi.sh) — PAS par cette application Flask, qui tourne sous un
utilisateur sans droits root et ne pourrait de toute façon pas piloter
NetworkManager en écriture à la demande.

Le fichier miroir existe parce que le script de veille (bash, lancé par
systemd, indépendant du process Flask) n'a pas d'accès pratique à la base
SQLite de l'appli. Régénéré à chaque enregistrement de "Réglages →
Réseau" (et une fois au démarrage de l'appli, pour le tout premier
démarrage avant même qu'un parent n'ait ouvert cette page). Restreint en
lecture au propriétaire (chmod 600) : root peut le lire quel que soit le
mode (il ignore les permissions Unix), donc ça ne gêne pas le script de
veille, mais ça évite qu'un autre utilisateur du système ne lise en clair
le mot de passe Wifi de la maison.
"""

import platform
import subprocess
import time

from app.config import DATA_DIR

FALLBACK_CONF_PATH = DATA_DIR / "wifi_fallback.conf"

# Nom de la connexion NetworkManager utilisée pour le point d'accès de
# secours — doit correspondre exactement à AP_CON_NAME dans
# bin/wifi-fallback-watchdog.sh.
AP_CONNECTION_NAME = "Contar-Secours"


def _clean(value: str) -> str:
    return (value or "").replace("\n", "").replace("\r", "").strip()


def write_fallback_conf(
    home_ssid: str, home_password: str, ap_enabled: bool, ap_ssid: str, ap_password: str,
) -> None:
    lines = [
        f"HOME_SSID={_clean(home_ssid)}",
        f"HOME_PASSWORD={_clean(home_password)}",
        f"AP_ENABLED={'1' if ap_enabled else '0'}",
        f"AP_SSID={_clean(ap_ssid)}",
        f"AP_PASSWORD={_clean(ap_password)}",
        "",
    ]
    FALLBACK_CONF_PATH.write_text("\n".join(lines), encoding="utf-8")
    try:
        FALLBACK_CONF_PATH.chmod(0o600)
    except Exception:
        pass  # PC de développement Windows, par exemple : sans conséquence.


def sync_fallback_conf() -> None:
    """
    Régénère le fichier miroir à partir des réglages enregistrés en base.
    Appelé au démarrage de l'appli (premier démarrage inclus) et à chaque
    enregistrement de "Réglages → Réseau".
    """
    from app.settings import SettingsManager  # import tardif : évite un cycle avec settings.py

    manager = SettingsManager()
    network = manager.get_network_config()
    fallback = manager.get_wifi_fallback_config()
    write_fallback_conf(
        home_ssid=network["wifi_ssid"],
        home_password=network["wifi_password"],
        ap_enabled=fallback["enabled"],
        ap_ssid=fallback["ssid"],
        ap_password=fallback["password"],
    )


def get_fallback_status() -> dict:
    """
    {"active": bool} — True si le point d'accès de secours est actuellement
    celui utilisé par la boîte (donc qu'elle N'EST PAS connectée au Wifi de
    la maison en ce moment). Uniquement de la lecture (nmcli), pas de sudo
    nécessaire — même principe que app/network_status.py.
    """
    status = {"active": False}
    if platform.system() != "Linux":
        return status
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME", "con", "show", "--active"],
            capture_output=True, text=True, timeout=3,
        )
        status["active"] = AP_CONNECTION_NAME in result.stdout.splitlines()
    except Exception:
        pass
    return status


# Adresse de la boîte sur son propre réseau de secours (fixée par
# NetworkManager pour un point d'accès partagé).
AP_ADDRESS = "10.42.0.1"

_cached_active = False
_cached_at = 0.0


def is_ap_active(max_age: float = 8.0) -> bool:
    """Comme get_fallback_status()["active"], mais sans relancer nmcli à
    chaque appel : la réponse est gardée max_age secondes. Sert au portail
    automatique (une vérification par page demandée) et à l'écran LCD."""
    global _cached_active, _cached_at
    now = time.monotonic()
    if now - _cached_at > max_age:
        _cached_active = get_fallback_status()["active"]
        _cached_at = now
    return _cached_active
