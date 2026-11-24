"""
Applique au système la configuration réseau saisie dans l'administration
(nom de la boîte, Wifi).

Depuis la v0.8, un nouveau Wifi est d'abord ESSAYÉ : il n'est adopté que
si la boîte s'y connecte vraiment ; sinon elle revient à son réglage
précédent ou rouvre son réseau de secours. Voir start_wifi_trial().

Comme pour le bouton "Éteindre" et la sortie audio : écrire le nom
d'hôte système et (re)configurer le Wifi demandent root, donc ça passe
par un script wrapper dédié (`bin/apply-network-config.sh`), autorisé en
sudo sans mot de passe UNIQUEMENT pour ce script précis (règle sudoers
posée par install_pi.sh) — jamais un accès root généralisé à
l'utilisateur du service.

Le mot de passe Wifi est transmis au script via son entrée standard
(stdin), pas en argument de ligne de commande, pour ne pas apparaître en
clair dans la liste des processus (`ps aux`) pendant l'exécution.
"""

import platform
import subprocess
import threading
import time

from app.config import DATA_DIR

APPLY_SCRIPT = "/opt/contar/bin/apply-network-config.sh"
FORGET_SCRIPT = "/opt/contar/bin/forget-wifi.sh"

# Compte rendu du dernier essai de Wifi, écrit par le script (qui tourne en
# root, détaché de la page web) et relu ici. Texte simple, une valeur par
# ligne : STATE (essai, ok, echec), SSID, REASON, IP, TIME.
TRIAL_STATE_PATH = DATA_DIR / "reseau_etat"

# Au-delà, un compte rendu resté sur « essai » est considéré comme perdu
# (coupure de courant pendant l'essai, par exemple).
TRIAL_MAX_SECONDS = 150


def _netmask_to_prefix(netmask: str) -> int:
    try:
        return sum(bin(int(octet)).count("1") for octet in netmask.strip().split("."))
    except Exception:
        return 24  # repli raisonnable (équivalent à 255.255.255.0)


def _script_input(wifi_ssid, wifi_password, ip_mode, static_ip, static_netmask, static_gateway, static_dns) -> str:
    if ip_mode == "static" and static_ip:
        ip_cidr = f"{static_ip}/{_netmask_to_prefix(static_netmask)}"
    else:
        ip_mode, ip_cidr = "dhcp", ""
    return f"{wifi_ssid}\n{wifi_password}\n{ip_mode}\n{ip_cidr}\n{static_gateway}\n{static_dns}\n"


def apply_hostname(hostname: str) -> tuple[bool, str]:
    """Change le nom de la boîte sur le réseau, sans toucher au Wifi.
    Rapide et sans coupure : on attend la fin du script."""
    if platform.system() != "Linux":
        return False, "La configuration réseau ne peut être appliquée que sur le vrai Raspberry Pi."
    try:
        result = subprocess.run(
            ["sudo", APPLY_SCRIPT, hostname], input="\n\ndhcp\n\n\n\n",
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            return True, "Nom de la boîte mis à jour."
        return False, f"Échec de l'application réseau : {result.stderr.strip() or result.stdout.strip() or 'erreur inconnue'}"
    except FileNotFoundError:
        return False, "Script de configuration réseau introuvable (réinstallez avec install_pi.sh)."
    except Exception as exc:
        return False, f"Impossible d'appliquer la configuration réseau : {exc}"


def start_wifi_trial(
    wifi_ssid: str, wifi_password: str,
    ip_mode: str = "dhcp", static_ip: str = "", static_netmask: str = "255.255.255.0",
    static_gateway: str = "", static_dns: str = "",
) -> tuple[bool, str]:
    """Lance l'essai d'un nouveau Wifi et revient TOUT DE SUITE.

    La boîte n'a qu'une carte Wifi : pendant l'essai, elle quitte le réseau
    par lequel la page a été ouverte (Wifi de la maison ou réseau de
    secours). Le script tourne donc détaché de la requête web, écrit son
    compte rendu dans TRIAL_STATE_PATH, et en cas d'échec remet lui-même
    la boîte dans l'état précédent (voir bin/apply-network-config.sh).
    Avant la v0.8, l'appel attendait le script, ignorait un échec de
    connexion et annonçait une réussite dans tous les cas."""
    if platform.system() != "Linux":
        return False, "La configuration réseau ne peut être appliquée que sur le vrai Raspberry Pi."
    try:
        process = subprocess.Popen(
            ["sudo", APPLY_SCRIPT, "-"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            text=True, start_new_session=True,
        )
        process.stdin.write(_script_input(
            wifi_ssid, wifi_password, ip_mode, static_ip, static_netmask, static_gateway, static_dns))
        process.stdin.close()
        # Évite de laisser un processus « zombie » une fois le script fini.
        threading.Thread(target=process.wait, daemon=True).start()
        return True, "Essai du Wifi lancé."
    except FileNotFoundError:
        return False, "Script de configuration réseau introuvable (réinstallez avec install_pi.sh)."
    except Exception as exc:
        return False, f"Impossible d'appliquer la configuration réseau : {exc}"


def read_trial_state() -> dict:
    """Dernier compte rendu d'essai : {"state", "ssid", "reason", "ip",
    "time", "age"}. "state" vaut "" s'il n'y a jamais eu d'essai."""
    state = {"state": "", "ssid": "", "reason": "", "ip": "", "time": "", "age": None}
    try:
        for line in TRIAL_STATE_PATH.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            key = key.strip().lower()
            if key in state:
                state[key] = value.strip()
    except OSError:
        return state
    try:
        state["age"] = max(0.0, time.time() - float(state["time"]))
    except ValueError:
        state["age"] = None
    if state["state"] == "essai" and state["age"] is not None and state["age"] > TRIAL_MAX_SECONDS:
        state["state"], state["reason"] = "echec", "interrompu"
    return state


def reconcile_after_trial() -> dict:
    """À appeler régulièrement (écran LCD, page Réseau). Si le dernier essai
    a échoué, remet dans les réglages le Wifi précédent — sans quoi la
    boîte garderait en mémoire un mot de passe refusé et le retenterait
    indéfiniment. Chaque compte rendu n'est traité qu'une fois."""
    from app import wifi_fallback
    from app.settings import SettingsManager

    state = read_trial_state()
    if state["state"] not in ("ok", "echec") or not state["time"]:
        return state
    manager = SettingsManager()
    if manager.get_last_handled_trial() == state["time"]:
        return state
    if state["state"] == "echec":
        manager.restore_previous_wifi()
        wifi_fallback.sync_fallback_conf()
    manager.set_last_handled_trial(state["time"])
    return state


def forget_wifi_network(ssid: str) -> tuple[bool, str]:
    """
    Supprime la connexion NetworkManager enregistrée pour ce SSID
    ("Oublier ce réseau") — utile pour repartir de zéro si le mot de
    passe a changé, ou avant de choisir un autre réseau depuis la liste
    déroulante. N'efface PAS le SSID/mot de passe enregistrés côté appli
    (Réglages → Réseau) : c'est à l'appelant de le faire s'il le souhaite
    (voir la route settings_network dans app/web/routes.py).
    """
    if platform.system() != "Linux":
        return False, "Impossible d'oublier un réseau : disponible uniquement sur le vrai Raspberry Pi."
    if not ssid:
        return False, "Aucun réseau à oublier."
    try:
        result = subprocess.run(
            ["sudo", FORGET_SCRIPT, ssid],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return True, result.stdout.strip().splitlines()[-1] if result.stdout.strip() else f"Réseau \"{ssid}\" oublié."
        return False, f"Échec : {result.stderr.strip() or result.stdout.strip() or 'erreur inconnue'}"
    except FileNotFoundError:
        return False, "Script introuvable (réinstallez avec install_pi.sh)."
    except Exception as exc:
        return False, f"Impossible d'oublier ce réseau : {exc}"


def forget_all_wifi_networks() -> tuple[bool, str]:
    """
    Supprime TOUTES les connexions Wifi enregistrées par NetworkManager
    (seul le point d'accès de secours "Contar-Secours" est épargné) — utilisé
    par la réinitialisation usine (app/factory_reset.py), PAS par "Oublier
    ce réseau" (qui ne vise qu'un SSID précis, voir forget_wifi_network
    ci-dessus).

    Contrairement à forget_wifi_network(), ne se limite pas au seul SSID
    connu de l'appli (settings.net_wifi_ssid) : une boîte a pu être
    connectée à d'AUTRES réseaux au fil du temps sans jamais repasser par
    "Oublier ce réseau" (Wifi configuré à la main via nmtui/raspi-config
    pendant l'installation, ancien propriétaire, déménagement...) — ces
    connexions resteraient sinon enregistrées après un reset usine,
    contrairement à ce qui est attendu ("qu'il ne reste que le wifi de
    secours").
    """
    if platform.system() != "Linux":
        return False, "Impossible d'oublier les réseaux Wifi : disponible uniquement sur le vrai Raspberry Pi."
    try:
        result = subprocess.run(
            ["sudo", FORGET_SCRIPT, "--toutes"],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            return True, result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "Tous les réseaux Wifi ont été oubliés."
        return False, f"Échec : {result.stderr.strip() or result.stdout.strip() or 'erreur inconnue'}"
    except FileNotFoundError:
        return False, "Script introuvable (réinstallez avec install_pi.sh)."
    except Exception as exc:
        return False, f"Impossible d'oublier les réseaux Wifi : {exc}"
