"""
Application effective du réglage "Énergie" (Réglages → Énergie) au
système : allumage/extinction des sorties HDMI, et gouverneur de
fréquence CPU (éco/performance). Le stockage du choix du parent vit dans
SettingsManager (voir app/settings.py), comme pour la sortie audio — ce
module-ci ne fait qu'appliquer ce choix au système, via
bin/set-power-mode.sh (root, sudoers restreint — même principe que
app/audio_output.py).

Contrairement à la sortie audio, aucun watchdog en continu n'est
nécessaire ici : rien ne "dérive" tout seul (pas de branchement/
débranchement externe à surveiller) — une application au démarrage du
service (voir app/web/__init__.py::create_app()) + à chaque changement
depuis Réglages suffit.

Point d'articulation important avec app/audio_output.py : si le son
passe actuellement par hdmi1/hdmi2, couper l'alimentation HDMI couperait
aussi le son — resolve_effective_hdmi() force donc HDMI allumé dans ce
cas précis, quel que soit le réglage "hdmi_enabled" choisi par ailleurs.
Décision du projet : "hdmi_enabled" est à False par défaut pour
économiser l'énergie, y compris sur une boîte qui utiliserait déjà HDMI
pour le son — dans ce cas le parent doit changer la sortie audio ou
réactiver l'HDMI lui-même depuis Réglages → Énergie ; ce module ne coupe
jamais le son tout seul.
"""

import platform
import subprocess

SET_POWER_SCRIPT = "/opt/contar/bin/set-power-mode.sh"


def resolve_effective_hdmi(hdmi_enabled: bool) -> bool:
    """L'HDMI reste TOUJOURS allumé si le son en dépend actuellement (voir
    app/audio_output.py::get_audio_output_preference()), quel que soit le
    réglage "hdmi_enabled" — jamais couper le son sans que le parent
    l'ait choisi explicitement en changeant la sortie audio elle-même."""
    from app.settings import SettingsManager

    preference = SettingsManager().get_audio_output_preference()
    if preference in ("hdmi1", "hdmi2"):
        return True
    return hdmi_enabled


def _run_script(*args: str) -> tuple[bool, str]:
    if platform.system() != "Linux":
        return False, "Le réglage énergie n'a d'effet que sur le vrai Raspberry Pi."
    try:
        result = subprocess.run(
            ["sudo", SET_POWER_SCRIPT, *args],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, f"Échec : {result.stderr.strip() or result.stdout.strip()}"
    except FileNotFoundError:
        return False, "Script de configuration énergie introuvable (réinstallez avec install_pi.sh)."
    except Exception as exc:
        return False, f"Impossible d'appliquer le réglage énergie : {exc}"


def apply_power_settings(hdmi_enabled: bool, eco_mode: bool) -> tuple[bool, str]:
    """Applique réellement les deux réglages au système. Appelée après
    chaque changement depuis Réglages → Énergie, et une fois au démarrage
    du service (voir apply_saved_power_settings())."""
    effective_hdmi = resolve_effective_hdmi(hdmi_enabled)
    ok_hdmi, msg_hdmi = _run_script("hdmi", "on" if effective_hdmi else "off")
    ok_cpu, msg_cpu = _run_script("cpu", "eco" if eco_mode else "performance")
    ok = ok_hdmi and ok_cpu
    message = " ".join(m for m in (msg_hdmi, msg_cpu) if m)
    return ok, message


def apply_saved_power_settings() -> None:
    """Réapplique le dernier réglage enregistré — appelée une fois au
    démarrage du service (voir app/web/__init__.py::create_app()), pour
    que la boîte reparte dans le bon état après chaque redémarrage, et
    aussi après un changement de sortie audio (voir
    app/web/routes.py::set_audio_output_preference()), au cas où ça
    change l'état HDMI effectif sans que le réglage énergie lui-même
    n'ait bougé."""
    from app.settings import SettingsManager

    settings_manager = SettingsManager()
    apply_power_settings(
        settings_manager.get_power_hdmi_enabled(),
        settings_manager.get_power_eco_mode(),
    )
