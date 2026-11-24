#!/bin/bash
# Applique un réglage "énergie" (Réglages → Énergie) : allumage/extinction
# des deux sorties HDMI, et gouverneur de fréquence CPU (éco/performance).
#
# Appelé UNIQUEMENT par app/power_settings.py (via sudo), jamais à la
# main. Script à part plutôt qu'un accès root généralisé — même principe
# que bin/set-audio-output.sh et bin/apply-network-config.sh : c'est CE
# script précis, et rien d'autre, qu'autorise la règle sudoers posée par
# install_pi.sh (/etc/sudoers.d/contar-energie).
#
# Usage :
#   set-power-mode.sh hdmi on|off
#   set-power-mode.sh cpu  eco|performance
set -euo pipefail

MODE="${1:?Usage: set-power-mode.sh <hdmi|cpu|wifi> <valeur>}"
VALUE="${2:?Usage: set-power-mode.sh <hdmi|cpu|wifi> <valeur>}"

case "$MODE" in
    hdmi)
        case "$VALUE" in
            on)
                # 2 = HDMI0, 7 = HDMI1 sur un Raspberry Pi 4 (identifiants
                # attendus par "vcgencmd display_power") — les deux sont
                # allumées/éteintes ensemble, pas de réglage indépendant
                # par port : pas besoin de plus fin pour cet usage.
                vcgencmd display_power 1 2 >/dev/null || true
                vcgencmd display_power 1 7 >/dev/null || true
                echo "HDMI allumé."
                ;;
            off)
                vcgencmd display_power 0 2 >/dev/null || true
                vcgencmd display_power 0 7 >/dev/null || true
                echo "HDMI éteint."
                ;;
            *)
                echo "Valeur HDMI invalide : $VALUE (attendu : on|off)" >&2
                exit 1
                ;;
        esac
        ;;
    cpu)
        case "$VALUE" in
            eco)
                GOVERNOR="powersave"
                ;;
            performance)
                # "ondemand" plutôt que "performance" : monte en fréquence
                # à la demande (déjà le comportement par défaut du Pi),
                # pas de plafond bas, sans pour autant tourner à fond en
                # continu pour rien.
                GOVERNOR="ondemand"
                ;;
            *)
                echo "Valeur CPU invalide : $VALUE (attendu : eco|performance)" >&2
                exit 1
                ;;
        esac
        for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
            [ -w "$f" ] && echo "$GOVERNOR" > "$f"
        done
        echo "Gouverneur CPU réglé sur : $GOVERNOR"
        ;;
    wifi)
        # Wi-Fi activé ou coupé (Réglages → Réseau, v0.11).
        case "$VALUE" in
            on)  nmcli radio wifi on;  echo "Wi-Fi activé." ;;
            off) nmcli radio wifi off; echo "Wi-Fi coupé." ;;
            *)
                echo "Valeur Wi-Fi invalide : $VALUE (attendu : on|off)" >&2
                exit 1
                ;;
        esac
        ;;
    *)
        echo "Mode invalide : $MODE (attendu : hdmi|cpu|wifi)" >&2
        exit 1
        ;;
esac
