#!/usr/bin/env python3
"""Applique en continu la règle de priorité de sortie audio ("Étape 24",
voir README.md) : un jack branché (via adaptateur audio USB) prend
TOUJOURS le dessus sur la préférence gpio/hdmi1/hdmi2 choisie dans
Réglages → Sortie audio, dès qu'il est détecté — y compris pendant une
lecture en cours, pas seulement au démarrage de la boîte.

Remplace l'ancien bin/reconnect_bluetooth_audio.py (ExecStartPre,
one-shot) par un service à part qui tourne EN CONTINU, sur le même
principe que bin/wifi-fallback-watchdog.sh : la bascule audio n'est pas
un événement ponctuel qu'on ne traite qu'au boot, c'est quelque chose qui
peut arriver à n'importe quel moment (on branche/débranche l'adaptateur
jack en cours d'écoute). Tourne sous le même utilisateur que le service
applicatif (User=$APP_USER dans l'unité) — mêmes droits sudo restreints
pour bin/set-audio-output.sh (voir install_pi.sh), pas besoin de root ici.

N'appelle audio_output.set_output() (qui redémarre le service applicatif,
voir bin/set-audio-output.sh) QUE quand la sortie effective a réellement
changé depuis le dernier passage — sinon ce service redémarrerait le
lecteur à chaque tour de boucle, coupant la lecture en cours pour rien.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.settings import SettingsManager  # noqa: E402
from app import audio_output  # noqa: E402

CHECK_INTERVAL_SECONDS = 5
BOOT_GRACE_SECONDS = 10  # laisse le temps aux cartes ALSA de s'énumérer au démarrage


def _tick(settings: SettingsManager) -> None:
    preference = settings.get_audio_output_preference()
    target = audio_output.resolve_effective_output(preference)
    if not target:
        return  # rien de détecté (PC de dev, ou boîte sans aucune carte visible) — on réessaiera au prochain tour

    current = settings.get_audio_output()
    if current and current.get("alsa_target") == target["alsa_target"]:
        return  # déjà la sortie active — rien à faire

    print(
        f"[audio-watchdog] Changement détecté : "
        f"{(current or {}).get('alsa_target', '(aucune)')} -> {target['alsa_target']} "
        f"({target['kind']}, {target['label']}).",
        flush=True,
    )
    ok, message = audio_output.set_output(target["alsa_target"])
    if ok:
        settings.set_audio_output(target["kind"], target["label"], target["alsa_target"])
        print(f"[audio-watchdog] Appliqué : {message}", flush=True)
    else:
        print(f"[audio-watchdog] Échec de l'application : {message}", flush=True)


def main() -> int:
    print(f"[audio-watchdog] Démarrage — délai de grâce de {BOOT_GRACE_SECONDS}s...", flush=True)
    time.sleep(BOOT_GRACE_SECONDS)

    settings = SettingsManager()
    while True:
        try:
            _tick(settings)
        except Exception as exc:
            # Une boucle de fond ne doit jamais s'arrêter sur une exception
            # isolée (carte ALSA qui disparaît en plein milieu d'un appel,
            # base de données momentanément verrouillée, etc.) — on
            # réessaiera simplement au prochain tour.
            print(f"[audio-watchdog] Exception ignorée ce tour-ci : {exc}", flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
