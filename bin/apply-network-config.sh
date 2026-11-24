#!/bin/bash
# apply-network-config.sh — applique le nom de la boîte et ESSAIE un Wifi.
#
# Lancé en root par l'administration (app/network_apply.py), grâce à une
# règle sudoers limitée à ce seul script (posée par install_pi.sh).
#
#   apply-network-config.sh <nom-de-la-boîte | ->
#   puis, sur l'entrée standard, une valeur par ligne :
#     nom du Wifi, mot de passe, dhcp|static, adresse/préfixe, passerelle, DNS
#   (le mot de passe passe par l'entrée standard pour ne jamais apparaître
#   dans la liste des processus).
#
# Principe de l'essai (v0.8) — la boîte n'a qu'une carte Wifi, elle ne peut
# pas rester joignable pendant qu'elle essaie un autre réseau. Donc :
#   1. on note à quoi elle est reliée (Wifi de la maison ou réseau de secours) ;
#   2. on crée un profil provisoire « contar-essai » et on tente de s'y
#      connecter pendant WAIT_SECONDS ;
#   3. réussite -> le profil provisoire devient le Wifi de la boîte ;
#      échec    -> profil supprimé, retour à l'état noté en 1.
# Le résultat est écrit dans data/reseau_etat, que l'administration et
# l'écran LCD relisent. Avant la v0.8, l'ancien profil était supprimé
# d'emblée et un échec passait inaperçu (« nmcli con up ... || true »).
#
# Variables d'environnement réservées aux essais hors boîte :
#   CONTAR_APP_DIR, CONTAR_LOCK_FILE, CONTAR_HOSTS_FILE, CONTAR_START_DELAY,
#   CONTAR_SCAN_DELAY

# Note : sous « set -o pipefail », « commande | grep -q motif » peut renvoyer
# un échec alors que le motif est trouvé (grep -q s'arrête au premier
# résultat et la commande en amont est interrompue). D'où « grep ... >/dev/null »
# partout dans ce script : grep lit alors toute l'entrée.
set -uo pipefail   # pas de -e : chaque échec est traité explicitement

APP_DIR="${CONTAR_APP_DIR:-/opt/contar}"
STATE_FILE="$APP_DIR/data/reseau_etat"
LOCK_FILE="${CONTAR_LOCK_FILE:-/run/contar-wifi-essai}"   # lu par wifi-fallback-watchdog.sh
AP_CON_NAME="Contar-Secours"                                # idem app/wifi_fallback.py
TRIAL_CON_NAME="contar-essai"
WAIT_SECONDS=40
START_DELAY="${CONTAR_START_DELAY:-2}"   # laisse la page « essai en cours » partir
SCAN_DELAY="${CONTAR_SCAN_DELAY:-5}"     # temps d'un balayage des réseaux

HOSTNAME_NEW="${1:?Usage: apply-network-config.sh <nom-de-la-boite | ->}"
IFS= read -r SSID || SSID=""
IFS= read -r PASSWORD || PASSWORD=""
IFS= read -r IP_MODE || IP_MODE="dhcp"
IFS= read -r IP_CIDR || IP_CIDR=""
IFS= read -r GATEWAY || GATEWAY=""
IFS= read -r DNS || DNS=""

log() { echo "[reseau] $*"; }

write_state() {   # write_state <essai|ok|echec> <raison> <adresse>
    local tmp="$STATE_FILE.tmp"
    mkdir -p "$(dirname "$STATE_FILE")"
    {
        printf 'STATE=%s\n' "$1"
        printf 'SSID=%s\n' "$SSID"
        printf 'REASON=%s\n' "$2"
        printf 'IP=%s\n' "$3"
        printf 'TIME=%s\n' "$(date +%s)"
    } > "$tmp"
    chmod 644 "$tmp"
    # Même propriétaire que le dossier de données : l'administration doit
    # pouvoir relire ce fichier, et data/ lui appartient.
    chown --reference="$(dirname "$STATE_FILE")" "$tmp" 2>/dev/null || true
    mv -f "$tmp" "$STATE_FILE"
}

wifi_device() {
    nmcli -t -f DEVICE,TYPE dev status 2>/dev/null | awk -F: '$2 == "wifi" {print $1; exit}'
}

active_wifi_connection() {   # nom de la connexion Wifi active, ou rien
    nmcli -t -f NAME,TYPE con show --active 2>/dev/null \
        | awk -F: '$NF == "802-11-wireless" {sub(/:802-11-wireless$/, ""); print; exit}' \
        | sed 's/\\:/:/g'   # nmcli -t écrit « \: » pour un deux-points dans un nom
}

connection_exists() { nmcli -t -f NAME con show 2>/dev/null | grep -Fx -- "$1" >/dev/null; }

# Sécurité annoncée par le réseau dans le dernier balayage ("WPA2", "WPA3",
# "WPA1 WPA2", vide pour un réseau ouvert) ; "?" si le réseau n'est pas vu
# (hors de portée, ou réseau caché).
scan_security() {
    local escaped line
    escaped="${SSID//\\/\\\\}"; escaped="${escaped//:/\\:}"   # nmcli -t protège \ et :
    while IFS= read -r line; do
        case "$line" in
            "$escaped":*) printf '%s' "${line#"$escaped":}"; return 0 ;;
        esac
    done < <(nmcli -t -f SSID,SECURITY dev wifi list ifname "$1" 2>/dev/null)
    printf '?'
}

# ---- 1. Nom de la boîte ------------------------------------------------------
# Changé seulement s'il est fourni ET différent du nom actuel.
if [ "$HOSTNAME_NEW" != "-" ] && [ -n "$HOSTNAME_NEW" ] && [ "$HOSTNAME_NEW" != "$(hostname)" ]; then
    HOSTS_FILE="${CONTAR_HOSTS_FILE:-/etc/hosts}"
    hostnamectl set-hostname "$HOSTNAME_NEW"
    if grep -q "^127\.0\.1\.1" "$HOSTS_FILE"; then
        sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$HOSTNAME_NEW/" "$HOSTS_FILE"
    else
        printf '127.0.1.1\t%s\n' "$HOSTNAME_NEW" >> "$HOSTS_FILE"
    fi
    systemctl restart avahi-daemon 2>/dev/null || true
    log "Nom de la boîte réglé sur : $HOSTNAME_NEW"
fi

if [ -z "$SSID" ]; then
    log "Aucun Wifi fourni : Wifi inchangé."
    exit 0
fi
if [ "$SSID" = "$AP_CON_NAME" ] || [ "$SSID" = "$TRIAL_CON_NAME" ]; then
    write_state echec "nom_reserve" ""
    log "Nom de Wifi réservé à la boîte : $SSID"
    exit 2
fi

# ---- 2. Essai du Wifi --------------------------------------------------------
DEV="$(wifi_device)"
if [ -z "$DEV" ]; then
    write_state echec "pas_de_carte" ""
    log "Aucune carte Wifi détectée."
    exit 2
fi

touch "$LOCK_FILE"                 # la veille du réseau de secours ne touche à rien pendant l'essai
trap 'rm -f "$LOCK_FILE"' EXIT
write_state essai "" ""
sleep "$START_DELAY"

PREVIOUS="$(active_wifi_connection)"
log "Essai du Wifi \"$SSID\" (état précédent : ${PREVIOUS:-aucune connexion Wifi})."

nmcli con delete "$TRIAL_CON_NAME" &>/dev/null || true
# Le réseau de secours occupe la carte : il faut le couper pour voir les
# réseaux alentour, puis laisser le temps d'un balayage.
if [ "$PREVIOUS" = "$AP_CON_NAME" ]; then
    nmcli con down "$AP_CON_NAME" &>/dev/null || true
fi
nmcli device wifi rescan ifname "$DEV" &>/dev/null || true
sleep "$SCAN_DELAY"

SECURITY="$(scan_security "$DEV")"
ADD_ARGS=(type wifi ifname "$DEV" con-name "$TRIAL_CON_NAME" ssid "$SSID" connection.autoconnect no)
if [ "$SECURITY" = "?" ]; then
    ADD_ARGS+=(802-11-wireless.hidden yes)   # pas vu : peut-être un réseau caché
fi
if [ -n "$PASSWORD" ]; then
    case "$SECURITY" in
        *WPA3*) case "$SECURITY" in
                    *WPA2*|*WPA1*) KEY_MGMT="wpa-psk" ;;   # réseau mixte : WPA2 suffit
                    *)             KEY_MGMT="sae" ;;       # WPA3 seul
                esac ;;
        *)      KEY_MGMT="wpa-psk" ;;
    esac
    ADD_ARGS+=(wifi-sec.key-mgmt "$KEY_MGMT" wifi-sec.psk "$PASSWORD")
fi
if [ "$IP_MODE" = "static" ] && [ -n "$IP_CIDR" ]; then
    ADD_ARGS+=(ipv4.method manual ipv4.addresses "$IP_CIDR")
    [ -n "$GATEWAY" ] && ADD_ARGS+=(ipv4.gateway "$GATEWAY")
    [ -n "$DNS" ] && ADD_ARGS+=(ipv4.dns "$DNS")
else
    ADD_ARGS+=(ipv4.method auto)
fi

OUT="$(nmcli con add "${ADD_ARGS[@]}" 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then
    OUT="$(nmcli --wait "$WAIT_SECONDS" con up "$TRIAL_CON_NAME" 2>&1)"; RC=$?
fi

if [ "$RC" -eq 0 ]; then
    # ---- 3a. Réussite : le profil provisoire devient le Wifi de la boîte ----
    IP="$(nmcli -g IP4.ADDRESS dev show "$DEV" 2>/dev/null | head -n1 | cut -d/ -f1)"
    if connection_exists "$SSID"; then
        nmcli con delete "$SSID" &>/dev/null || true   # ancien profil du même réseau
    fi
    nmcli con mod "$TRIAL_CON_NAME" connection.id "$SSID" connection.autoconnect yes &>/dev/null || true
    write_state ok "" "$IP"
    log "Wifi \"$SSID\" adopté (adresse : ${IP:-inconnue})."
    exit 0
fi

# ---- 3b. Échec : on remet la boîte comme elle était -------------------------
case "$OUT" in
    *ecrets*|*psk*|*assword*|*handshake*)   REASON="mot_de_passe" ;;
    *"not be found"*|*"No network"*|*ssid-not-found*) REASON="introuvable" ;;
    *)
        if [ "$SECURITY" = "?" ]; then REASON="introuvable"; else REASON="autre"; fi ;;
esac
log "Échec de l'essai ($REASON) : ${OUT:-erreur inconnue}"
nmcli con delete "$TRIAL_CON_NAME" &>/dev/null || true

RESTORED=0
if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$AP_CON_NAME" ] && connection_exists "$PREVIOUS"; then
    if nmcli --wait 30 con up "$PREVIOUS" &>/dev/null; then
        RESTORED=1
        log "Retour au Wifi précédent \"$PREVIOUS\"."
    fi
fi
if [ "$RESTORED" -eq 0 ] && connection_exists "$AP_CON_NAME"; then
    if nmcli --wait 20 con up "$AP_CON_NAME" &>/dev/null; then
        log "Réseau de secours rouvert."
    fi
    # Sinon la veille (wifi-fallback-watchdog.sh) s'en charge au cycle suivant.
fi
write_state echec "$REASON" ""
exit 2
