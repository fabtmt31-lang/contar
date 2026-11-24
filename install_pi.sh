#!/usr/bin/env bash
#
# install_pi.sh — installe Contar, la boîte à histoires Audiolibre, sur un Raspberry Pi
# (Raspberry Pi OS, avec ou sans bureau — Lite recommandé).
#
# La boîte n'a ni écran d'ordinateur ni clavier : elle se pilote entièrement
# depuis son administration web, ouverte depuis un téléphone, une tablette
# ou un ordinateur du même réseau (http://contar.local).
#
# Deux façons de piloter les actions de base (lecture/pause, avance/recul,
# volume) sont supportées :
#   - "gamepad" (par défaut) : une manette USB filaire type NES/Super NES
#     branchée sur le Pi — rien à câbler, on branche et ça marche.
#   - "gpio"    : 5 boutons-poussoirs câblés sur les broches GPIO, pour
#     une vraie boîte assemblée plus tard (voir app/controls/gpio_controller.py
#     pour le câblage attendu).
#
# À exécuter EN ROOT, sur le Raspberry Pi lui-même :
#   sudo bash install_pi.sh [chemin_vers_le_projet] [gamepad|gpio]
#
# Si aucun chemin n'est donné, le script suppose qu'il est lui-même situé
# à la racine du projet (à côté de run_pi.py, requirements.txt, etc.).
# Si aucun mode n'est donné, "gamepad" est utilisé par défaut.
#
# Exemples :
#   sudo bash install_pi.sh                        # mode manette, chemin auto
#   sudo bash install_pi.sh . gpio                  # mode GPIO, projet dans le dossier courant
#   sudo bash install_pi.sh /home/pi/contar gamepad
#
# Rejouable sans risque (idempotent) : relancez-le (au besoin avec un
# mode différent, pour basculer manette <-> GPIO) sans perdre les
# histoires/musiques déposées ni la base de données existante.

set -euo pipefail

# ---------------------------------------------------------------------------
# 0. Vérifications préalables
# ---------------------------------------------------------------------------

if [ "$(id -u)" -ne 0 ]; then
    echo "Ce script doit être lancé en root : sudo bash install_pi.sh" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${1:-$SCRIPT_DIR}"
CONTROL_MODE="${2:-gamepad}"

if [ "$CONTROL_MODE" != "gamepad" ] && [ "$CONTROL_MODE" != "gpio" ]; then
    echo "Mode de contrôle inconnu : '$CONTROL_MODE' (attendu : gamepad ou gpio)" >&2
    exit 1
fi

if [ ! -f "$SOURCE_DIR/run_pi.py" ]; then
    echo "Impossible de trouver run_pi.py dans : $SOURCE_DIR" >&2
    echo "Indiquez le bon chemin : sudo bash install_pi.sh /chemin/vers/contar" >&2
    exit 1
fi

APP_USER="contar"
APP_DIR="/opt/contar"
SERVICE_NAME="contar"

if [ "$CONTROL_MODE" = "gamepad" ]; then
    RUN_SCRIPT="run_pi_gamepad.py"
else
    RUN_SCRIPT="run_pi.py"
fi

log() { echo -e "\n\033[1;32m==> $*\033[0m"; }

# ---------------------------------------------------------------------------
# 1. Clavier console en AZERTY FR
# ---------------------------------------------------------------------------
# Même une Raspberry Pi OS installée/configurée en français peut laisser
# les consoles texte (celle branchée en HDMI+clavier, ou un accès série)
# en QWERTY US par défaut — ce qui fausse la saisie des mots de passe et
# des commandes. On le corrige ici de façon persistante (prochains
# démarrages) ET immédiate (console actuelle).

log "Configuration du clavier en AZERTY français..."
if [ -f /etc/default/keyboard ]; then
    if grep -q '^XKBLAYOUT=' /etc/default/keyboard; then
        sed -i 's/^XKBLAYOUT=.*/XKBLAYOUT="fr"/' /etc/default/keyboard
    else
        echo 'XKBLAYOUT="fr"' >> /etc/default/keyboard
    fi
else
    cat > /etc/default/keyboard <<'EOF'
XKBMODEL="pc105"
XKBLAYOUT="fr"
XKBVARIANT=""
XKBOPTIONS=""
EOF
fi

# Persiste le réglage pour les prochains démarrages.
setupcon --save 2>/dev/null || true
# Applique tout de suite sur la console courante, si on en a une (peut
# échouer silencieusement si le script tourne via SSH sans TTY local
# associé — sans conséquence, seul le prochain démarrage compte alors).
loadkeys fr 2>/dev/null || true

# ---------------------------------------------------------------------------
# 2. Accès SSH activé par défaut
# ---------------------------------------------------------------------------

log "Activation de l'accès SSH..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
if ! dpkg -s openssh-server &>/dev/null; then
    apt-get install -y openssh-server
fi
systemctl enable --now ssh

# ---------------------------------------------------------------------------
# 3. Paquets système restants
# ---------------------------------------------------------------------------

log "Installation des paquets système..."
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    vlc \
    rsync \
    alsa-utils \
    network-manager \
    avahi-daemon \
    dnsmasq-base \
    pcscd \
    libccid \
    libpcsclite-dev \
    swig \
    i2c-tools \
    iw \
    nftables

# ---------------------------------------------------------------------------
# 4. mDNS (http://<nom>.local) : nécessite avahi-daemon actif.
# ---------------------------------------------------------------------------

log "Activation d'avahi-daemon (résolution http://<nom>.local)..."
systemctl enable --now avahi-daemon 2>/dev/null || \
    echo "[!] avahi-daemon n'a pas pu démarrer — l'adresse http://<nom>.local pourrait ne pas fonctionner (utilisez l'adresse IP à la place)."

# Service système du lecteur NFC/RFID (étape 29) : nécessaire pour tout
# lecteur PC/SC (Omnikey, adaptateurs CCID...) branché en USB — la lib
# Python pyscard ne parle jamais directement au lecteur, uniquement à ce
# service, qui gère le matériel à sa place.
log "Activation de pcscd (lecteur NFC/RFID)..."
systemctl enable --now pcscd 2>/dev/null || \
    echo "[!] pcscd n'a pas pu démarrer — le lecteur NFC/RFID ne sera pas détecté."

# Par défaut, pcscd (Debian/Raspberry Pi OS) refuse l'accès à tout
# processus qui n'appartient pas à une session locale active (protection
# contre un accès distant non autorisé aux cartes à puce) — ce qui bloque
# systématiquement $APP_USER, qui tourne en service systemd headless,
# jamais dans une vraie session graphique/console. Sans cette règle,
# pyscard échoue avec "Access denied" (SCARD_W_SECURITY_VIOLATION) dès le
# premier appel, quel que soit le lecteur branché.
log "Autorisation polkit pour l'accès au lecteur NFC/RFID..."
mkdir -p /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/49-contar-pcsc.rules <<EOF
polkit.addRule(function(action, subject) {
    if ((action.id == "org.debian.pcsc-lite.access_pcsc" || action.id == "org.debian.pcsc-lite.access_card")
        && subject.user == "$APP_USER") {
        return polkit.Result.YES;
    }
});
EOF
systemctl restart polkit 2>/dev/null || true

# ---------------------------------------------------------------------------
# 5. Utilisateur dédié à la boîte
# ---------------------------------------------------------------------------

if ! id "$APP_USER" &>/dev/null; then
    log "Création de l'utilisateur $APP_USER..."
    useradd -m -s /bin/bash "$APP_USER"
else
    log "Utilisateur $APP_USER déjà présent."
fi

# audio -> sortie son ; gpio -> lecture/écriture directe des broches GPIO
# sans droits root (groupe fourni par Raspberry Pi OS) ; input -> lecture
# directe de la manette USB (/dev/input/event*). On ajoute les deux
# groupes GPIO et input dans tous les cas : ça ne coûte rien et permet de
# rejouer ce script plus tard avec l'autre mode sans souci de permissions.
usermod -aG audio,gpio,input "$APP_USER"

# 6. Copie du projet
# ---------------------------------------------------------------------------

# ---- Reprise d'une ancienne installation (« Histoires du Soir », avant la v0.8)
# Jusqu'à la v0.7.1, la boîte s'installait dans /opt/histoiresdusoir, sous
# l'utilisateur hds, avec des services histoiresdusoir-*. Si on trouve cette
# installation, on arrête ses services, on retire ses autorisations, et on
# DÉPLACE (sans copier : pas de double place sur la carte) ses histoires,
# ses musiques et sa base vers les nouveaux emplacements. Les chemins
# enregistrés dans la base sont corrigés plus bas, une fois Python prêt
# (tools/migrate_old_install.py). Sans ancienne installation, rien ne se passe.
OLD_DIR="/opt/histoiresdusoir"
OLD_USER="hds"
MIGRATED=0
if [ -d "$OLD_DIR" ]; then
    log "Ancienne installation trouvée dans $OLD_DIR : reprise sous le nom Contar..."
    for OLD_UNIT in histoiresdusoir histoiresdusoir-wifi-fallback histoiresdusoir-audio-watchdog; do
        systemctl disable --now "$OLD_UNIT".service 2>/dev/null || true
        rm -f /etc/systemd/system/"$OLD_UNIT".service
    done
    rm -f /etc/sudoers.d/histoiresdusoir-* \
          /etc/polkit-1/rules.d/49-histoiresdusoir-pcsc.rules \
          /etc/udev/rules.d/99-histoiresdusoir-input.rules
    systemctl daemon-reload
    nmcli con delete "HDS-Secours" &>/dev/null || true   # ancien profil du réseau de secours

    mkdir -p "$APP_DIR"
    if [ -d "$OLD_DIR/HDP" ] && [ ! -e "$APP_DIR/Bibliotheque" ]; then
        mv "$OLD_DIR/HDP" "$APP_DIR/Bibliotheque"
    fi
    if [ -d "$OLD_DIR/data" ] && [ ! -e "$APP_DIR/data" ]; then
        mv "$OLD_DIR/data" "$APP_DIR/data"
    fi
    if [ -f "$APP_DIR/data/histoiresdusoir.db" ] && [ ! -e "$APP_DIR/data/contar.db" ]; then
        mv "$APP_DIR/data/histoiresdusoir.db" "$APP_DIR/data/contar.db"
    fi
    MIGRATED=1
fi

log "Copie du projet vers $APP_DIR..."
mkdir -p "$APP_DIR"
# On protège Bibliotheque/ (histoires/musiques déposées), data/ (base de données +
# jaquettes) et venv/ (environnement Python) d'un écrasement lors d'une
# mise à jour : --delete supprime les fichiers de code retirés, mais ces
# trois dossiers sont explicitement épargnés.
rsync -a --delete \
    --exclude 'venv/' \
    --exclude 'data/' \
    --exclude 'Bibliotheque/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "$SOURCE_DIR"/ "$APP_DIR"/

mkdir -p "$APP_DIR"/Bibliotheque/Livres "$APP_DIR"/Bibliotheque/Musiques "$APP_DIR"/data/covers
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

# ---------------------------------------------------------------------------
# 7. Environnement Python
# ---------------------------------------------------------------------------

log "Installation des dépendances Python (venv)..."
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip

# lgpio (dépendance d'adafruit-blinka, nécessaire au bus I2C du PN532/de
# l'écran LCD — même sans utiliser une seule broche GPIO directement) ne
# se compile PAS depuis les sources sur Raspberry Pi OS Trixie : le
# paquet source suppose une lib C "liblgpio" déjà installée
# séparément, absente par défaut ("cannot find -llgpio" à l'édition de
# liens). Adafruit fournit un wheel précompilé statiquement lié pour ce
# cas précis (Python 3.13 / aarch64, exactement la config par défaut de
# Trixie sur Pi 4) : on l'installe EN PREMIER, pour que gpiozero (mode
# GPIO) et adafruit-blinka (PN532/écran) le trouvent déjà satisfait
# ensuite et ne tentent jamais la compilation depuis les sources.
log "Installation de lgpio (wheel précompilé, évite l'échec de compilation sur Trixie)..."
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install \
    "https://github.com/adafruit/lgpio-python-wheels/raw/main/wheels/lgpio-0.2.2.0-cp313-cp313-linux_aarch64.whl" || \
    echo "[!] Wheel lgpio précompilé indisponible (pas d'accès Internet au moment de l'install ?) — la compilation depuis les sources sera tentée juste après, et peut échouer (voir GUIDE_RASPBERRY.md)."

sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ "$MIGRATED" -eq 1 ]; then
    log "Reprise de l'ancienne installation : mise à jour des chemins dans la base..."
    if sudo -u "$APP_USER" "$APP_DIR/venv/bin/python" "$APP_DIR/tools/migrate_old_install.py" "$OLD_DIR" "$APP_DIR"; then
        # Ne retire l'ancien dossier que si histoires et base en sont bien parties.
        if [ ! -e "$OLD_DIR/HDP" ] && [ ! -e "$OLD_DIR/data" ]; then
            rm -rf "$OLD_DIR"
            userdel -r "$OLD_USER" 2>/dev/null || true
            log "Ancienne installation retirée."
        else
            echo "[!] $OLD_DIR contient encore des données (une installation Contar existait déjà ?) : dossier laissé en place, à vérifier à la main."
        fi
    else
        echo "[!] La mise à jour des chemins a échoué : $OLD_DIR est laissé en place. Relancez install_pi.sh, ou voyez GUIDE_RASPBERRY.md."
    fi
fi

if [ "$CONTROL_MODE" = "gpio" ]; then
    # lgpio est déjà installé juste au-dessus (wheel précompilé) dans la
    # quasi-totalité des cas — cet appel ne fait donc normalement rien de
    # plus ("already satisfied"), gardé comme filet de sécurité si jamais
    # le wheel précompilé n'était pas accessible au moment de l'install.
    sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install lgpio || \
        echo "[!] Installation de lgpio échouée — si gpiozero ne trouve pas de broches au démarrage, voir GUIDE_RASPBERRY.md (section dépannage)."
else
    # "inputs" est déjà dans requirements.txt (installé juste au-dessus) :
    # rien de plus à faire côté paquets pour le mode manette.
    log "Mode manette USB : configuration de l'accès direct au périphérique..."
    cat > /etc/udev/rules.d/99-contar-input.rules <<'EOF'
# Autorise le groupe "input" à lire les périphériques d'entrée USB
# (manette) sans droits root — nécessaire à gamepad_controller.py.
SUBSYSTEM=="input", GROUP="input", MODE="0660"
EOF
    udevadm control --reload-rules
    udevadm trigger
fi

# ---------------------------------------------------------------------------
# 8. Droit d'éteindre le Pi depuis l'interface web (bouton "Réglages")
# ---------------------------------------------------------------------------
# L'appli tourne sous l'utilisateur $APP_USER (jamais root) et exécute
# "sudo shutdown -h now" quand on clique sur Éteindre. Sans règle sudoers
# dédiée, cette commande resterait bloquée en attente d'un mot de passe
# qui n'arrivera jamais (le service n'a pas de terminal). Cette règle
# n'autorise QUE la commande shutdown, rien d'autre, sans mot de passe.

log "Autorisation du bouton Éteindre (sudoers)..."
cat > /etc/sudoers.d/contar-shutdown <<EOF
$APP_USER ALL=(root) NOPASSWD: /sbin/shutdown
EOF
chmod 440 /etc/sudoers.d/contar-shutdown
visudo -c -f /etc/sudoers.d/contar-shutdown

# Même principe pour la page Réglages → Sortie audio : écrire
# /etc/asound.conf demande root, mais UNIQUEMENT via ce script précis
# (app/audio_output.py l'appelle en sudo), jamais un accès root généralisé.
log "Autorisation du changement de sortie audio (sudoers)..."
chmod +x "$APP_DIR/bin/set-audio-output.sh"
cat > /etc/sudoers.d/contar-audio <<EOF
$APP_USER ALL=(root) NOPASSWD: $APP_DIR/bin/set-audio-output.sh
EOF
chmod 440 /etc/sudoers.d/contar-audio
visudo -c -f /etc/sudoers.d/contar-audio

# Même principe pour la page Réglages → Réseau : appliquer le nom d'hôte
# et le Wifi au système demande root, mais UNIQUEMENT via ce script précis.
log "Autorisation de l'application de la config réseau (sudoers)..."
chmod +x "$APP_DIR/bin/apply-network-config.sh"
cat > /etc/sudoers.d/contar-reseau <<EOF
$APP_USER ALL=(root) NOPASSWD: $APP_DIR/bin/apply-network-config.sh
EOF
chmod 440 /etc/sudoers.d/contar-reseau
visudo -c -f /etc/sudoers.d/contar-reseau

# Même principe pour "Oublier ce réseau" (Réglages → Réseau) : supprimer
# une connexion NetworkManager demande root aussi, mais UNIQUEMENT via ce
# script précis.
log "Autorisation d'oublier un réseau Wifi (sudoers)..."
chmod +x "$APP_DIR/bin/forget-wifi.sh"
cat > /etc/sudoers.d/contar-oubli-wifi <<EOF
$APP_USER ALL=(root) NOPASSWD: $APP_DIR/bin/forget-wifi.sh
EOF
chmod 440 /etc/sudoers.d/contar-oubli-wifi
visudo -c -f /etc/sudoers.d/contar-oubli-wifi

# Même principe pour la page Réglages → Énergie : allumer/éteindre l'HDMI
# (vcgencmd) et changer le gouverneur CPU (écriture dans /sys) demandent
# root aussi, mais UNIQUEMENT via ce script précis.
log "Autorisation du réglage énergie (sudoers)..."
chmod +x "$APP_DIR/bin/set-power-mode.sh"
cat > /etc/sudoers.d/contar-energie <<EOF
$APP_USER ALL=(root) NOPASSWD: $APP_DIR/bin/set-power-mode.sh
EOF
chmod 440 /etc/sudoers.d/contar-energie
visudo -c -f /etc/sudoers.d/contar-energie

# Import par clé USB (v0.9) : l'appli tourne sans droits root et ne peut
# donc pas relier une clé elle-même. Ce script le fait pour elle, toujours
# en lecture seule, et refuse tout ce qui n'est pas une clé USB — voir
# bin/usb-key.sh et app/usb_import.py.
log "Autorisation de lire une clé USB (sudoers)..."
chmod +x "$APP_DIR/bin/usb-key.sh"
cat > /etc/sudoers.d/contar-cle-usb <<EOF
$APP_USER ALL=(root) NOPASSWD: $APP_DIR/bin/usb-key.sh
EOF
chmod 440 /etc/sudoers.d/contar-cle-usb
visudo -c -f /etc/sudoers.d/contar-cle-usb

# ---------------------------------------------------------------------------
# 9. Point d'accès Wifi de secours ("Wifi Direct")
# ---------------------------------------------------------------------------
# Si la boîte n'arrive pas à se connecter au Wifi de la maison (jamais
# configuré, mot de passe faux/changé, borne hors de portée), elle doit
# pouvoir créer son propre réseau Wifi pour être reconfigurée sans écran
# ni câble Ethernet. Contrairement au bouton "Éteindre" ou à la sortie
# audio, ce n'est pas une action ponctuelle déclenchée par l'appli (donc
# pas de sudoers dédié ici) : c'est une surveillance en continu, qui tourne
# dans SON PROPRE service systemd, lancé directement en root (jamais sous
# l'utilisateur de l'appli, qui n'aurait de toute façon pas le droit de
# piloter NetworkManager). Voir bin/wifi-fallback-watchdog.sh et
# app/wifi_fallback.py pour le détail du fonctionnement.

log "Installation du point d'accès Wifi de secours..."
chmod +x "$APP_DIR/bin/wifi-fallback-watchdog.sh"

# Page ouverte toute seule sur le réseau de secours. Sur ce réseau, c'est
# NetworkManager qui répond aux demandes d'adresses des appareils
# connectés ; ce réglage lui fait répondre « la boîte » à toutes. Un
# téléphone qui vient de se connecter croit alors à un portail d'accès
# (comme sur le Wifi d'un hôtel) et propose d'ouvrir la page — voir
# app/web/__init__.py::captive_portal. Ne concerne QUE le réseau de secours.
#
# Depuis la v0.9, ce fichier est réécrit par bin/wifi-fallback-watchdog.sh
# à chaque ouverture du réseau de secours (voir portal_setup dans ce
# script) : la valeur ci-dessous n'est que le réglage de départ.
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
cat > /etc/NetworkManager/dnsmasq-shared.d/contar-portail.conf <<'EOF'
# Contar : sur le réseau de secours, toute adresse demandée mène à la boîte.
address=/#/10.42.0.1
EOF
cat > /etc/systemd/system/contar-wifi-secours.service <<EOF
[Unit]
Description=Contar - réseau Wifi de secours
After=NetworkManager.service network.target
Wants=NetworkManager.service

[Service]
Type=simple
ExecStart=$APP_DIR/bin/wifi-fallback-watchdog.sh
Restart=always
RestartSec=5
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now contar-wifi-secours.service
# Lors d'une mise à jour, le service tourne déjà avec l'ancien script :
# on le relance pour qu'il prenne le nouveau. Cela ne coupe pas le réseau.
systemctl restart contar-wifi-secours.service

# ---------------------------------------------------------------------------
# 10. Service de bascule automatique de la sortie audio (watchdog)
# ---------------------------------------------------------------------------
# Remplace l'ancienne reconnexion Bluetooth au démarrage (bin/
# reconnect_bluetooth_audio.py, retiré — voir README.md "Étape 24") par
# un service à part qui tourne EN CONTINU (même principe que le watchdog
# Wifi de secours ci-dessus) : un jack (adaptateur USB) branché doit
# prendre le dessus sur gpio/hdmi1/hdmi2 dès qu'il est détecté, y compris
# en cours de lecture — pas seulement au démarrage de la boîte. Tourne
# sous le même utilisateur que le service applicatif (mêmes droits sudo
# restreints pour bin/set-audio-output.sh, voir section 8) — pas besoin
# de root ici. Voir bin/audio_output_watchdog.py pour le détail.

log "Installation du service de bascule automatique de la sortie audio..."
chmod +x "$APP_DIR/bin/audio_output_watchdog.py"
cat > /etc/systemd/system/contar-audio.service <<EOF
[Unit]
Description=Contar - bascule automatique de la sortie audio (jack prioritaire)
After=sound.target
Wants=sound.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/bin/audio_output_watchdog.py
Restart=always
RestartSec=5
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now contar-audio.service

# Ampli MAX98357A tenu en éveil (v0.10.2). Cet ampli s'endort dès que le Pi
# cesse de lui envoyer du son, et se réveille avec un souffle bref : on
# l'entendait à chaque lancement et à chaque reprise de lecture. Remède
# habituel pour ce composant : lui envoyer du silence en permanence.
# - « contar_ampli » est un mélangeur (dmix) posé sur la carte de l'ampli :
#   plusieurs programmes peuvent y jouer en même temps (le silence, la
#   lecture, les bips de la boîte) ;
# - contar-ampli.service y joue du silence sans fin. Sans ampli déclaré sur
#   le Pi, ce service ne fait rien (il revérifie de temps en temps).
log "Installation du maintien en éveil de l'ampli..."
mkdir -p /etc/alsa/conf.d
cat > /etc/alsa/conf.d/60-contar-ampli.conf <<'EOF'
# Contar : mélangeur partagé de l'ampli MAX98357A. Voir install_pi.sh.
pcm.contar_ampli {
    type dmix
    ipc_key 983570
    ipc_perm 0666
    slave {
        pcm "hw:MAX98357A,0"
        format S16_LE
        rate 44100
        channels 2
        period_size 1024
        buffer_size 8192
    }
    bindings {
        0 0
        1 1
    }
}

# Les deux canaux réunis en un seul (v0.10.3). L'ampli n'a qu'un
# haut-parleur ; selon le branchement de sa broche SD il joue la moyenne
# des deux canaux, ou le canal gauche seulement (SD reliée au 3,3 V). En
# lui envoyant la même chose sur les deux, rien ne se perd dans les deux cas.
pcm.contar_ampli_mono {
    type route
    slave.pcm "contar_ampli"
    slave.channels 2
    ttable.0.0 0.5
    ttable.1.0 0.5
    ttable.0.1 0.5
    ttable.1.1 0.5
}
EOF
# Réglage en place d'une version précédente : il s'adressait à l'ampli
# directement, ce qui n'est plus possible une fois le mélangeur en service.
if [ -f /etc/asound.conf ]; then
    sed -i 's#slave.pcm "hw:MAX98357A,0"#slave.pcm "contar_ampli_mono"#; s#slave.pcm "contar_ampli"#slave.pcm "contar_ampli_mono"#' /etc/asound.conf
fi
cat > /etc/systemd/system/contar-ampli.service <<EOF
[Unit]
Description=Contar - ampli tenu en éveil (pas de souffle au début des lectures)
After=sound.target
Wants=sound.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
ExecStartPre=/bin/sh -c 'test -e /proc/asound/MAX98357A'
ExecStart=/usr/bin/aplay -q -D contar_ampli -t raw -f S16_LE -r 44100 -c 2 /dev/zero
Restart=always
RestartSec=20
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable contar-ampli.service
systemctl restart contar-ampli.service 2>/dev/null || true

# ---------------------------------------------------------------------------
# 11. Service systemd principal
# ---------------------------------------------------------------------------

log "Installation du service systemd $SERVICE_NAME..."
cat > /etc/systemd/system/"$SERVICE_NAME".service <<EOF
[Unit]
Description=Contar - serveur applicatif (Raspberry Pi, mode $CONTROL_MODE)
After=network.target sound.target
Wants=sound.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
# Port 80 (adresse sans numéro de port : http://contar.local). Ce port est
# réservé à root ; cette ligne en donne le droit, et lui seul, au service.
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/$RUN_SCRIPT
Restart=always
RestartSec=2
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME".service
systemctl restart "$SERVICE_NAME".service

# ---------------------------------------------------------------------------
# 12. Optimisations matérielles (Bluetooth, LEDs, caméra/écran) + I2C
# ---------------------------------------------------------------------------
# Désactivations permanentes au niveau matériel, décidées pour réduire la
# chaleur et la consommation (objectif à terme : fonctionnement sur
# batterie) — contrairement au réglage "Énergie" (HDMI, CPU, voir
# Réglages → Énergie / app/power_settings.py), rien ici n'est
# configurable depuis l'interface : ces éléments ne sont utilisés nulle
# part dans le projet, les couper n'a donc aucun inconvénient
# fonctionnel.
# - Bluetooth : retiré du projet depuis longtemps (voir README.md
#   "Étape 24"), plus aucun usage nulle part — dtoverlay=disable-bt coupe
#   la puce radio elle-même, pas juste le service.
# - LEDs d'activité/alimentation : objet posé dans une chambre d'enfant,
#   une LED qui clignote en continu la nuit n'a rien d'un avantage.
# - Détection caméra/écran (firmware Bookworm+) : la boîte n'utilise
#   jamais ni caméra ni écran branché en direct sur le Pi (l'écran LCD
#   prévu se pilote en I2C, pas via cette détection-là) — évite un
#   sondage inutile à chaque démarrage.
# - I2C : activé (dtparam=i2c_arm=on), CETTE FOIS pour ajouter du
#   matériel plutôt qu'en retirer — bus partagé par le lecteur NFC PN532
#   (app/tag_reader.py::PN532Reader) et l'écran LCD (app/lcd_display.py),
#   chacun à sa propre adresse. $APP_USER ajouté au groupe "i2c" pour
#   accéder à /dev/i2c-1 sans root (device déjà réservé à ce groupe par
#   défaut sur Raspberry Pi OS).
# Redémarrage nécessaire pour que ces changements prennent effet — pas
# fait automatiquement ici, pour ne jamais couper une boîte déjà en
# cours d'utilisation en plein milieu d'une installation.

if [ -f /boot/firmware/config.txt ]; then
    CONFIG_TXT=/boot/firmware/config.txt
elif [ -f /boot/config.txt ]; then
    CONFIG_TXT=/boot/config.txt
else
    CONFIG_TXT=""
fi

if [ -n "$CONFIG_TXT" ]; then
    # dtoverlay=max98357a,no-sdmode (v0.10.1) : ampli de la boîte, un
    # MAX98357A branché sur les broches (5 V, masse, BCLK = GPIO18, LRC =
    # GPIO19, DIN = GPIO21). Il apparaît alors comme une carte son
    # « MAX98357A », que la boîte choisit d'elle-même pour ses
    # haut-parleurs (app/audio_output.py). Sans ampli branché, cette ligne
    # est sans effet audible.
    log "Optimisations matérielles (Bluetooth, LEDs, caméra/écran) + I2C + ampli dans $CONFIG_TXT..."
    for LINE in \
        "dtoverlay=disable-bt" \
        "dtparam=act_led_trigger=none" \
        "dtparam=pwr_led_trigger=none" \
        "camera_auto_detect=0" \
        "display_auto_detect=0" \
        "dtparam=i2c_arm=on" \
        "dtoverlay=max98357a,no-sdmode"
    do
        grep -qxF "$LINE" "$CONFIG_TXT" || echo "$LINE" >> "$CONFIG_TXT"
    done
    systemctl disable --now hciuart 2>/dev/null || true
    systemctl disable --now bluetooth 2>/dev/null || true
    usermod -aG i2c "$APP_USER" 2>/dev/null || true
    # dtparam=i2c_arm=on active le contrôleur I2C matériel, mais ne crée
    # PAS /dev/i2c-1 à lui seul : il faut aussi charger le module noyau
    # générique "i2c-dev" (piège découvert en test réel — sans cette
    # ligne, /dev/i2c-1 disparaît de nouveau à CHAQUE redémarrage).
    grep -qxF "i2c-dev" /etc/modules || echo "i2c-dev" >> /etc/modules
    modprobe i2c-dev 2>/dev/null || true
    REBOOT_NEEDED=1
else
    echo "[!] Fichier config.txt introuvable — optimisations matérielles (Bluetooth/LEDs/caméra) et I2C non appliqués."
    REBOOT_NEEDED=0
fi

# ---------------------------------------------------------------------------
# Fin
# ---------------------------------------------------------------------------

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')

log "Installation terminée ! (mode de contrôle : $CONTROL_MODE)"
cat <<EOF

La boîte tourne déjà (service $SERVICE_NAME actif, redémarre automatiquement
au boot et en cas de plantage).
EOF

if [ "$CONTROL_MODE" = "gamepad" ]; then
    cat <<EOF

Branchez la manette USB (NES/Super NES ou compatible) sur le Pi si ce
n'est pas déjà fait — elle est prise en compte automatiquement, aucun
redémarrage nécessaire. Pour vérifier qu'elle est bien reconnue :
  $APP_DIR/venv/bin/python $APP_DIR/test_gamepad.py
EOF
fi

cat <<EOF

Administration, depuis un téléphone, une tablette ou un ordinateur relié
au même réseau :
  http://$(hostname).local
  http://${IP_ADDR:-<adresse-de-la-boîte>}        (si la première ne répond pas)
Cette adresse s'affiche aussi sur l'écran de la boîte au démarrage.

Si la boîte n'arrive pas à rejoindre le Wifi de la maison (pas encore
réglé, ou hors de portée), elle ouvre au bout d'une minute environ son
propre réseau Wifi de secours : « Contar-Secours », mot de passe
« audiolibre » par défaut (les deux s'affichent sur son écran). Reliez-y
un téléphone : la page de la boîte s'ouvre en général toute seule ; sinon,
ouvrez http://10.42.0.1.

Accès SSH (depuis un autre PC) :
  ssh $(logname 2>/dev/null || echo "<votre-utilisateur>")@${IP_ADDR:-<IP-du-Pi>}

En cas de souci :
  - Logs du serveur : journalctl -u $SERVICE_NAME -f
  - Redémarrer après une modif du code : sudo systemctl restart $SERVICE_NAME
  - Voir GUIDE_RASPBERRY.md pour le détail (dépannage, pièges classiques)

Pour appliquer une mise à jour du code, ou basculer manette <-> GPIO :
recopiez le projet sur le Pi puis relancez
  sudo bash install_pi.sh . gamepad     # ou : gpio
EOF

if [ "${REBOOT_NEEDED:-0}" = "1" ]; then
    cat <<EOF

⚠ Un redémarrage est nécessaire (une seule fois) pour que les
optimisations matérielles (Bluetooth désactivé, LEDs éteintes, détection
caméra/écran désactivée) et l'activation de l'I2C (lecteur NFC PN532 +
écran LCD) prennent effet :
  sudo reboot
La boîte redémarre ensuite automatiquement dessus, comme d'habitude.
EOF
fi
