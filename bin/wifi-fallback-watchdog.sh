#!/bin/bash
# wifi-fallback-watchdog.sh — bascule automatiquement vers un point
# d'accès Wifi de secours ("Wifi Direct") quand la boîte n'arrive pas à
# se connecter au Wifi de la maison (jamais configuré, mot de passe
# faux/changé, borne hors de portée...).
#
# Tourne en continu, EN ROOT, via son propre service systemd
# (contar-wifi-secours.service, installé par install_pi.sh) —
# volontairement indépendant du service applicatif (qui tourne, lui, sous
# un utilisateur sans droits root et ne pourrait de toute façon pas créer
# de point d'accès Wifi lui-même).
#
# Lit sa configuration dans un fichier miroir écrit par l'appli Flask à
# chaque enregistrement de "Réglages → Réseau" (voir app/wifi_fallback.py
# — l'appli n'a pas non plus les droits root nécessaires pour piloter
# NetworkManager en écriture, donc tout passe par ce script séparé). Le
# fichier est lu ligne à ligne (jamais "source"é) pour ne jamais risquer
# d'exécuter du contenu arbitraire si un mot de passe contenait des
# caractères spéciaux du shell.
#
# Principe : ce Pi n'a qu'une seule carte Wifi, donc il ne peut pas être
# à la fois connecté au Wifi de la maison ET diffuser son propre point
# d'accès — c'est l'un ou l'autre. Par défaut on laisse sa chance au Wifi
# de la maison (mode normal) ; si aucune connexion n'est établie après un
# court délai de grâce (le temps de démarrer proprement), on bascule sur
# le point d'accès de secours pour que le Wifi de la maison puisse être
# reconfiguré depuis un téléphone connecté dessus. Ensuite, régulièrement,
# on retente une connexion au Wifi de la maison — dès qu'elle réussit, le
# point d'accès de secours est coupé automatiquement.

# Note : sous « set -o pipefail », « commande | grep -q motif » peut renvoyer
# un échec alors que le motif est trouvé (grep -q s'arrête au premier
# résultat et la commande en amont est interrompue). D'où « grep ... >/dev/null »
# partout dans ce script : grep lit alors toute l'entrée.
set -uo pipefail  # pas de -e : ce script tourne en boucle infinie, une
                   # commande qui échoue ne doit jamais l'arrêter.

APP_DIR="${CONTAR_APP_DIR:-/opt/contar}"
CONF_FILE="$APP_DIR/data/wifi_fallback.conf"
# Posé par bin/apply-network-config.sh pendant l'essai d'un nouveau Wifi :
# tant qu'il est là (et récent), cette veille ne touche à rien.
LOCK_FILE="${CONTAR_LOCK_FILE:-/run/contar-wifi-essai}"
LOCK_MAX_AGE_SECONDS=180
AP_CON_NAME="Contar-Secours"          # doit correspondre à AP_CONNECTION_NAME dans app/wifi_fallback.py
# Durées réglables par variables d'environnement, pour les essais hors boîte uniquement.
BOOT_GRACE_SECONDS="${CONTAR_BOOT_GRACE:-45}"            # laisse une chance au Wifi de la maison au démarrage
CHECK_INTERVAL_SECONDS="${CONTAR_CHECK_INTERVAL:-30}"
RETRY_HOME_EVERY_CYCLES="${CONTAR_RETRY_CYCLES:-6}"      # ~3 minutes en mode secours avant de retenter la maison

# Page ouverte toute seule sur le réseau de secours (voir portal_setup).
PORTAL_CONF="${CONTAR_PORTAL_CONF:-/etc/NetworkManager/dnsmasq-shared.d/contar-portail.conf}"
PORTAL_TABLE="contar_portail"
PORTAL_NET="10.42.0.0/24"       # réseau de secours (fixé par NetworkManager)
PORTAL_BOX_IP="10.42.0.1"       # adresse de la boîte sur ce réseau
PORTAL_OUTSIDE_IP="192.0.2.1"   # adresse « extérieure » de façade, voir ci-dessous
PORTAL_MODE=""

log() { echo "[wifi-fallback] $*"; }

# Page ouverte toute seule sur le réseau de secours.
#
# Un téléphone qui rejoint un Wifi interroge une adresse de test de son
# fabricant. Si la réponse est détournée vers une page, il affiche « Se
# connecter au réseau » et ouvre cette page : c'est ce qu'on veut.
#
# En v0.8, la boîte répondait à tous les noms par sa propre adresse
# (10.42.0.1). Cela suffit à un iPhone ou à Windows, mais beaucoup de
# téléphones Android (Samsung en tête) écartent ce cas : un nom Internet
# qui mène à une adresse privée, ils en concluent « pas d'Internet » et
# n'ouvrent rien.
#
# Depuis la v0.9, la boîte répond donc par une adresse d'apparence
# extérieure, et une règle du pare-feu ramène vers elle tout le trafic web
# (port 80) émis sur le réseau de secours. Si l'outil nft n'est pas
# disponible, on garde l'ancienne méthode.
portal_rules_present() {
    nft list table ip "$PORTAL_TABLE" >/dev/null 2>&1
}

portal_install_rules() {
    command -v nft >/dev/null 2>&1 || return 1
    nft delete table ip "$PORTAL_TABLE" >/dev/null 2>&1 || true
    nft -f - >/dev/null 2>&1 <<EOF
table ip $PORTAL_TABLE {
    chain prerouting {
        type nat hook prerouting priority -100; policy accept;
        ip saddr $PORTAL_NET ip daddr != $PORTAL_NET tcp dport 80 redirect to :80
    }
    chain forward {
        type filter hook forward priority -1; policy accept;
        ip saddr $PORTAL_NET ip daddr != $PORTAL_NET tcp dport 443 reject with tcp reset
    }
}
EOF
}

portal_write_conf() {
    local answer="$1"
    mkdir -p "$(dirname "$PORTAL_CONF")" 2>/dev/null || return 0
    {
        echo "# Contar : sur le réseau de secours, toute adresse demandée mène à la boîte."
        echo "# Fichier réécrit par bin/wifi-fallback-watchdog.sh — ne pas modifier à la main."
        echo "address=/#/$answer"
    } > "$PORTAL_CONF" 2>/dev/null || true
}

# Appelé au démarrage et avant chaque ouverture du réseau de secours : pose
# les règles si elles manquent, et règle la réponse aux noms en conséquence.
portal_setup() {
    local mode="simple"
    if portal_rules_present || portal_install_rules; then
        mode="complet"
    fi
    if [ "$mode" = "complet" ]; then
        portal_write_conf "$PORTAL_OUTSIDE_IP"
    else
        portal_write_conf "$PORTAL_BOX_IP"
    fi
    if [ "$mode" != "$PORTAL_MODE" ]; then
        PORTAL_MODE="$mode"
        if [ "$mode" = "complet" ]; then
            log "Page automatique du réseau de secours : prête (redirection du trafic web)."
        else
            log "Page automatique du réseau de secours : méthode simple (outil nft indisponible)."
        fi
    fi
}

wifi_device() {
    nmcli -t -f DEVICE,TYPE dev status 2>/dev/null | awk -F: '$2 == "wifi" {print $1; exit}'
}

read_conf() {
    HOME_SSID=""; HOME_PASSWORD=""; AP_ENABLED="1"; AP_SSID="Contar-Secours"; AP_PASSWORD=""
    [ -f "$CONF_FILE" ] || return 0
    local key value
    while IFS='=' read -r key value; do
        case "$key" in
            HOME_SSID) HOME_SSID="$value" ;;
            HOME_PASSWORD) HOME_PASSWORD="$value" ;;
            AP_ENABLED) AP_ENABLED="$value" ;;
            AP_SSID) AP_SSID="$value" ;;
            AP_PASSWORD) AP_PASSWORD="$value" ;;
        esac
    done < "$CONF_FILE"
}

is_connected_to_home_wifi() {
    # Vrai s'il existe une connexion Wifi active dont le nom n'est PAS
    # celui du point d'accès de secours.
    nmcli -t -f NAME,TYPE con show --active 2>/dev/null | \
        awk -F: -v ap="$AP_CON_NAME" '$2 == "802-11-wireless" && $1 != ap {found=1} END {exit !found}'
}

# Vrai si un essai de Wifi est en cours. Un verrou trop vieux (script
# interrompu par une coupure de courant, par exemple) est ignoré et retiré.
trial_in_progress() {
    [ -e "$LOCK_FILE" ] || return 1
    local age=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
    if [ "$age" -gt "$LOCK_MAX_AGE_SECONDS" ]; then
        rm -f "$LOCK_FILE"
        return 1
    fi
    return 0
}

# Vrai si au moins un appareil (téléphone, ordinateur) est relié au réseau
# de secours. Avant la v0.8, la boîte quittait le réseau de secours toutes
# les 3 minutes pour retenter le Wifi de la maison, même pendant qu'un
# parent était en train de la configurer : la page se coupait sous ses doigts.
ap_has_clients() {
    local dev
    dev="$(wifi_device)"
    [ -n "$dev" ] || return 1
    iw dev "$dev" station dump 2>/dev/null | grep -- '^Station' >/dev/null
}

is_ap_active() {
    nmcli -t -f NAME con show --active 2>/dev/null | grep -x -- "$AP_CON_NAME" >/dev/null
}

start_ap() {
    is_ap_active && return 0
    if [ -z "$AP_PASSWORD" ] || [ "${#AP_PASSWORD}" -lt 8 ]; then
        log "Mot de passe du point d'accès de secours absent ou trop court (min. 8 caractères) — abandon."
        return 1
    fi
    local dev
    dev="$(wifi_device)"
    if [ -z "$dev" ]; then
        log "Aucune carte Wifi détectée — impossible d'activer le point d'accès de secours."
        return 1
    fi
    # Retour de test réel : tant que le Wifi de la maison reste visible,
    # NetworkManager retente tout seul de s'y connecter avec le profil
    # enregistré (comportement "autoconnect" standard, indépendant de ce
    # script) — même si ça échoue en boucle (mot de passe faux, par
    # exemple). Ça peut monopoliser la carte Wifi et empêcher la création
    # du point d'accès de secours tant que cette tentative est en cours,
    # ce qui donnait l'impression que la bascule n'avait lieu QUE si le
    # Wifi de la maison disparaissait complètement. On libère donc
    # explicitement la carte de toute tentative en cours avant de créer
    # le point d'accès — sans effet si elle était déjà libre.
    nmcli device disconnect "$dev" &>/dev/null || true

    portal_setup

    log "Aucune connexion au Wifi de la maison — activation du point d'accès de secours \"$AP_SSID\"..."
    # Le profil est recréé à chaque ouverture, avec le nom et le mot de passe
    # du moment : avant la v0.8, un profil déjà existant était réactivé tel
    # quel, si bien qu'un nom ou un mot de passe changé dans Réglages →
    # Réseau n'était jamais pris en compte.
    local out
    nmcli con delete "$AP_CON_NAME" &>/dev/null || true
    out="$(nmcli device wifi hotspot ifname "$dev" con-name "$AP_CON_NAME" ssid "$AP_SSID" password "$AP_PASSWORD" 2>&1)"
    if is_ap_active; then
        log "Point d'accès de secours actif : \"$AP_SSID\" (rejoignez-le puis ouvrez http://10.42.0.1 pour reconfigurer le Wifi)."
    else
        log "Échec de l'activation du point d'accès de secours : ${out:-erreur inconnue}"
    fi
}

stop_ap() {
    if is_ap_active; then
        log "Point d'accès de secours coupé."
        nmcli con down "$AP_CON_NAME" &>/dev/null || true
    fi
}

# Wifi enregistré hors de l'administration (à la préparation de la carte SD
# avec Raspberry Pi Imager, par exemple) : l'administration n'en connaît ni
# le nom ni le mot de passe, mais NetworkManager a son profil. On le
# retente tel quel. Avant la v0.8, une boîte dans ce cas ne quittait plus
# jamais son réseau de secours une fois qu'elle y était passée.
try_saved_wifi_profiles() {
    local name type
    while IFS=: read -r name type; do
        [ "$type" = "802-11-wireless" ] || continue
        [ "$name" = "$AP_CON_NAME" ] && continue
        [ "$name" = "contar-essai" ] && continue
        log "Tentative de reconnexion au Wifi enregistré \"$name\"..."
        if nmcli --wait 30 con up "$name" &>/dev/null; then
            return 0
        fi
    done < <(nmcli -t -f NAME,TYPE con show 2>/dev/null)
    return 1
}

try_home_wifi() {
    if [ -z "$HOME_SSID" ]; then
        try_saved_wifi_profiles
        return $?
    fi
    log "Tentative de reconnexion au Wifi de la maison \"$HOME_SSID\"..."
    # "local out=$(...)" masquerait le code retour de la commande (celui
    # de "local" lui-même) : déclaration et affectation séparées exprès.
    local out rc
    if nmcli -t -f NAME con show 2>/dev/null | grep -Fx -- "$HOME_SSID" >/dev/null; then
        # Profil déjà enregistré (créé par l'essai réussi d'un Wifi, voir
        # bin/apply-network-config.sh) : on le réactive tel quel, avec ses
        # réglages d'adresse.
        out="$(nmcli --wait 30 con up "$HOME_SSID" 2>&1)"
    elif [ -n "$HOME_PASSWORD" ]; then
        out="$(nmcli --wait 30 device wifi connect "$HOME_SSID" password "$HOME_PASSWORD" 2>&1)"
    else
        out="$(nmcli --wait 30 device wifi connect "$HOME_SSID" 2>&1)"
    fi
    rc=$?
    if [ "$rc" -ne 0 ]; then
        log "Échec de la connexion au Wifi de la maison : ${out:-erreur inconnue}"
    fi
    return "$rc"
}

portal_setup

log "Démarrage — délai de grâce de ${BOOT_GRACE_SECONDS}s avant la première vérification..."
sleep "$BOOT_GRACE_SECONDS"

cycle=0
while true; do
    if trial_in_progress; then
        sleep 5
        continue
    fi

    read_conf

    # Wi-Fi coupé par un parent (Réglages → Réseau, v0.11) : rien à faire,
    # la boîte se règle alors par le câble USB-C.
    if nmcli radio wifi 2>/dev/null | grep -qi '^disabled'; then
        sleep "$CHECK_INTERVAL_SECONDS"
        continue
    fi

    if [ "$AP_ENABLED" != "1" ]; then
        # Fonction désactivée par un parent : on s'assure juste que le
        # point d'accès n'est pas resté actif d'une session précédente.
        stop_ap
        sleep "$CHECK_INTERVAL_SECONDS"
        continue
    fi

    if is_ap_active; then
        # Règles effacées entre-temps (pare-feu rechargé, par exemple) : on les remet.
        portal_rules_present || [ "$PORTAL_MODE" != "complet" ] || portal_install_rules || true
        cycle=$((cycle + 1))
        if [ "$cycle" -ge "$RETRY_HOME_EVERY_CYCLES" ]; then
            cycle=0
            if ap_has_clients; then
                log "Un appareil est relié au réseau de secours : pas de nouvel essai du Wifi de la maison pour l'instant."
            elif try_home_wifi && is_connected_to_home_wifi; then
                log "Wifi de la maison retrouvé."
                stop_ap
            else
                # L'essai a libéré la carte Wifi : on rouvre le réseau de
                # secours tout de suite, sans attendre le cycle suivant.
                start_ap
            fi
        fi
    else
        if is_connected_to_home_wifi; then
            cycle=0
        else
            start_ap
        fi
    fi

    sleep "$CHECK_INTERVAL_SECONDS"
done
