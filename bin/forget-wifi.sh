#!/bin/bash
# forget-wifi.sh — supprime une ou plusieurs connexions Wifi enregistrées
# par NetworkManager.
#
#   forget-wifi.sh <ssid>    "Oublier ce réseau" (Réglages → Réseau) :
#                             supprime UNE connexion précise.
#   forget-wifi.sh --toutes  Réinitialisation usine (app/factory_reset.py) :
#                             supprime TOUTES les connexions Wifi
#                             enregistrées (type 802-11-wireless), y
#                             compris celles jamais passées par cette
#                             appli (connectées à la main via nmtui/
#                             raspi-config pendant l'installation, ou
#                             restes d'un ancien propriétaire) — seule la
#                             connexion du point d'accès de secours
#                             ("Contar-Secours", voir AP_CONNECTION_NAME dans
#                             app/wifi_fallback.py et AP_CON_NAME dans
#                             bin/wifi-fallback-watchdog.sh, à garder
#                             identique aux deux endroits) est épargnée,
#                             pour qu'il reste disponible juste après le
#                             redémarrage qui suit un reset usine.
#
# Appelé UNIQUEMENT par app/network_apply.py (via sudo), jamais à la
# main. Volontairement un script à part plutôt qu'un accès root
# généralisé : c'est CE script précis qu'autorise la règle sudoers posée
# par install_pi.sh (/etc/sudoers.d/contar-oubli-wifi) — sans
# restriction d'arguments, donc "--toutes" est déjà couvert par cette
# même règle, pas besoin d'une règle sudoers séparée.
# Note : sous « set -o pipefail », « commande | grep -q motif » peut renvoyer
# un échec alors que le motif est trouvé (grep -q s'arrête au premier
# résultat et la commande en amont est interrompue). D'où « grep ... >/dev/null »
# partout dans ce script : grep lit alors toute l'entrée.
set -euo pipefail

AP_CONNECTION_NAME="Contar-Secours"

ARG="${1:?Usage: forget-wifi.sh <ssid> | forget-wifi.sh --toutes}"

if [ "$ARG" = "--toutes" ]; then
    COUNT=0
    # -t (tabulaire, sans en-tête) -f NAME,TYPE : une ligne "nom:type" par
    # connexion enregistrée, y compris celles jamais actives. On ne garde
    # que le Wifi classique (802-11-wireless) — pas le point d'accès de
    # secours, qui doit survivre au reset.
    while IFS=: read -r name type; do
        [ "$type" = "802-11-wireless" ] || continue
        [ "$name" = "$AP_CONNECTION_NAME" ] && continue
        # "|| true" : un échec isolé (connexion déjà partie entre-temps,
        # etc.) ne doit jamais interrompre la boucle avant d'avoir essayé
        # les autres — surtout avec "set -e" actif plus haut.
        if nmcli con delete "$name"; then
            COUNT=$((COUNT + 1))
        fi
    done < <(nmcli -t -f NAME,TYPE con show)
    echo "$COUNT réseau(x) Wifi oublié(s) (point d'accès de secours conservé)."
else
    SSID="$ARG"
    if nmcli -t -f NAME con show | grep -Fx -- "$SSID" >/dev/null; then
        nmcli con delete "$SSID"
        echo "Réseau \"$SSID\" oublié."
    else
        echo "Aucune connexion enregistrée pour \"$SSID\" (déjà oublié ?)."
    fi
fi
