#!/bin/bash
# Écrit /etc/asound.conf pour pointer la sortie audio par défaut vers la
# cible ALSA donnée en argument, par exemple :
#   hw:Headphones,0     (haut-parleurs GPIO, selon le nom de carte réel)
#   hw:Device,0         (jack, via adaptateur audio USB)
#   hw:vc4hdmi0,0       (HDMI 1)
#   hw:vc4hdmi1,0       (HDMI 2)
#
# Appelé UNIQUEMENT par app/audio_output.py (via sudo), jamais à la main.
# Volontairement un script à part plutôt qu'un accès root généralisé :
# c'est CE script précis, et rien d'autre, qu'autorise la règle sudoers
# posée par install_pi.sh (/etc/sudoers.d/contar-audio) — même
# principe que pour le bouton "Éteindre".
set -euo pipefail

TARGET="${1:?Usage: set-audio-output.sh <cible ALSA>}"

# Ampli de la boîte (MAX98357A) : on ne s'adresse pas à lui directement mais
# à « contar_ampli », un mélangeur partagé défini par install_pi.sh dans
# /etc/alsa/conf.d/60-contar-ampli.conf (v0.10.2). Un petit service y joue
# du silence en permanence (contar-ampli.service) : l'ampli ne s'endort
# plus entre deux lectures, ce qui supprime le souffle bref entendu à chaque
# lancement ou reprise. Le mélangeur laisse aussi les bips de la boîte se
# superposer à une histoire en cours.
AMP_CARD="MAX98357A"
AMP_PCM="contar_ampli_mono"     # les deux canaux réunis, puis le mélangeur contar_ampli
AMP_CONF="/etc/alsa/conf.d/60-contar-ampli.conf"

if [[ "$TARGET" == hw:* ]]; then
    # Le "card" pour ctl.!default est le nom de carte seul (avant la virgule).
    CARD="${TARGET#hw:}"
    CARD="${CARD%%,*}"
    SLAVE="$TARGET"
    if [ "$CARD" = "$AMP_CARD" ] && [ -f "$AMP_CONF" ]; then
        SLAVE="$AMP_PCM"
    fi
    cat > /etc/asound.conf <<EOF
pcm.!default {
    type plug
    slave.pcm "$SLAVE"
}
ctl.!default {
    type hw
    card $CARD
}
EOF
else
    # Cible non "hw:..." (rare — atteignable seulement via le champ
    # "Sortie manuelle" de Réglages → Sortie audio) : pas de "card" ALSA
    # classique à cibler pour ctl.!default, on ne règle que pcm.!default.
    cat > /etc/asound.conf <<EOF
pcm.!default {
    type plug
    slave.pcm "$TARGET"
}
EOF
fi

echo "Sortie audio par défaut réglée sur : $TARGET"

# Retour de test réel : casque Bluetooth appairé, connecté, sélectionné
# comme sortie, lecture sans la moindre erreur — mais silence total,
# jusqu'à un redémarrage manuel du service. Cause : la bibliothèque ALSA
# lit /etc/asound.conf UNE SEULE FOIS par processus (mise en cache dès
# la première ouverture d'un périphérique audio) — le service
# contar déjà en cours d'exécution, qui a quasi certainement
# déjà ouvert un périphérique audio au moins une fois, ne relit donc
# jamais ce fichier tout seul après une modification. On redémarre donc
# le service nous-mêmes pour forcer une lecture fraîche. En tâche de
# fond avec un délai : ce script est appelé DEPUIS une requête web traitée
# par ce même service, il faut la laisser répondre normalement avant que
# le processus qui la sert ne soit coupé.
#
# Retour de test réel : avec 1 seconde de délai, la route "Associer un
# appareil Bluetooth" (qui fait déjà pair+trust+connect avant d'arriver
# ici, donc déjà plusieurs secondes de traitement) affichait parfois "Cette
# page ne fonctionne pas" côté navigateur — la reconnexion Bluetooth avait
# pourtant bien réussi côté serveur (son fonctionnel après avoir rechargé
# la page à la main). Le redémarrage coupait donc la réponse HTTP de CETTE
# requête avant qu'elle ait fini de partir. Délai remonté à 3 secondes,
# large marge de sécurité pour laisser partir une réponse même après un
# traitement déjà long.
(sleep 3; systemctl restart contar 2>/dev/null || true) &
disown 2>/dev/null || true
