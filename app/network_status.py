"""
Détecte le Wifi réellement connecté (et l'adresse IP actuelle) via les
outils système du Raspberry Pi (NetworkManager) — jusqu'ici, la page
Réglages réseau ne montrait que la configuration ENREGISTRÉE, jamais ce
à quoi l'appareil est vraiment connecté.

Uniquement de la lecture (nmcli, hostname), rien de destructif. Renvoie
des valeurs vides plutôt que de lever une exception si les commandes ne
sont pas disponibles (PC de développement Windows/Mac, ou Pi sans Wifi
actif pour l'instant) — cette page doit toujours pouvoir s'afficher.
"""

import platform
import re
import subprocess


def _split_terse(line: str) -> list[str]:
    """
    Découpe une ligne de sortie `nmcli -t` sur les ":" non échappés — nmcli
    échappe les ":" qui apparaissent DANS une valeur (un SSID peut en
    contenir un) en "\\:", donc un simple line.split(":") les couperait
    au mauvais endroit.
    """
    parts = re.split(r"(?<!\\):", line)
    return [p.replace("\\:", ":") for p in parts]


def scan_wifi_networks() -> list[dict]:
    """
    Réseaux Wifi visibles à proximité : [{"ssid", "signal" (0-100),
    "secured" (bool)}, ...], du plus fort au plus faible signal, sans
    doublon de SSID (garde la meilleure occurrence si plusieurs bornes
    diffusent le même nom — répéteur/mesh).

    "nmcli device wifi rescan" demande un scan actif frais avant de lire
    la liste ; ni l'un ni l'autre ne demandent de droits root pour la
    LECTURE (contrairement à s'y connecter, qui reste géré par
    app/network_apply.py via le script sudoers dédié). Si le scan échoue
    (adaptateur absent, PC de développement...), liste vide plutôt qu'une
    exception — la saisie manuelle du SSID reste toujours possible côté
    interface.
    """
    if platform.system() != "Linux":
        return []
    try:
        subprocess.run(["nmcli", "device", "wifi", "rescan"], capture_output=True, timeout=5)
    except Exception:
        pass  # tant pis, on retente avec ce que nmcli a déjà en cache

    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
            capture_output=True, text=True, timeout=8,
        )
    except Exception:
        return []

    entries = []
    for line in result.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) < 3:
            continue
        ssid, signal = parts[0], parts[1]
        security = ":".join(parts[2:])
        if not ssid:
            continue  # réseau caché (SSID vide) : pas affichable dans une liste, saisie manuelle
        try:
            signal_val = int(signal)
        except ValueError:
            signal_val = 0
        entries.append({"ssid": ssid, "signal": signal_val, "secured": bool(security.strip())})

    entries.sort(key=lambda n: n["signal"], reverse=True)
    seen = set()
    networks = []
    for net in entries:
        if net["ssid"] in seen:
            continue
        seen.add(net["ssid"])
        networks.append(net)
    return networks


def get_wifi_status() -> dict:
    """{"connected_ssid": str|None, "ip_address": str|None}"""
    status = {"connected_ssid": None, "ip_address": None}
    if platform.system() != "Linux":
        return status

    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
            capture_output=True, text=True, timeout=3,
        )
        for line in result.stdout.splitlines():
            if line.startswith("yes:"):
                ssid = line.split(":", 1)[1].strip()
                status["connected_ssid"] = ssid or None
                break
    except Exception:
        pass

    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3)
        first = (result.stdout or "").split()
        status["ip_address"] = first[0] if first else None
    except Exception:
        pass

    return status


def lcd_summary() -> dict:
    """Résumé de l'état du réseau pour l'écran de la boîte :
    {"mode": "essai" | "secours" | "ok" | "echec" | "wifi" | "filaire" | "aucun",
     "ssid": str, "ip": str, "password": str}

    "ok" et "echec" ne durent qu'une minute après un essai de Wifi, le
    temps d'être lus sur la boîte ; ensuite on retombe sur l'état courant."""
    from app import wifi_fallback
    from app.network_apply import read_trial_state
    from app.settings import SettingsManager

    summary = {"mode": "aucun", "ssid": "", "ip": "", "password": ""}
    trial = read_trial_state()
    recent = trial["age"] is not None and trial["age"] < 60
    if trial["state"] == "essai":
        summary.update(mode="essai", ssid=trial["ssid"])
        return summary

    if wifi_fallback.is_ap_active(max_age=4.0):
        fallback = SettingsManager().get_wifi_fallback_config()
        mode = "echec" if (trial["state"] == "echec" and recent) else "secours"
        summary.update(mode=mode, ssid=fallback["ssid"], password=fallback["password"],
                       ip=wifi_fallback.AP_ADDRESS)
        return summary

    status = get_wifi_status()
    ip = status["ip_address"] or ""
    if status["connected_ssid"]:
        mode = "ok" if (trial["state"] == "ok" and recent) else "wifi"
        summary.update(mode=mode, ssid=status["connected_ssid"], ip=ip)
    elif ip:
        summary.update(mode="filaire", ip=ip)
    return summary
