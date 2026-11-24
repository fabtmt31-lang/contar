#!/bin/bash
# update-contar.sh — installe une nouvelle version de Contar téléchargée
# depuis GitHub par l'administration (Réglages → Mise à jour, app/updater.py).
#
#   update-contar.sh <archive.tar.gz>
#
# L'archive est celle que GitHub fournit pour une version (un dossier
# racine qui contient install_pi.sh et run_pi.py). Le script relance
# install_pi.sh dessus, avec le mode de contrôle déjà en place (manette ou
# boutons) : bibliothèque, base et réglages sont conservés.
#
# install_pi.sh redémarre le service contar : pour ne pas être interrompu
# avec lui, ce script se relance d'abord hors du service (systemd-run),
# puis rend la main tout de suite à l'administration. Journal :
# /opt/contar/data/maj/derniere-maj.log
#
# Appelé par app/updater.py via sudo (règle sudoers posée par install_pi.sh).

set -euo pipefail

APP_DIR="/opt/contar"
ARCHIVE="${1:?Usage : update-contar.sh <archive.tar.gz>}"
LOG="$APP_DIR/data/maj/derniere-maj.log"

case "$ARCHIVE" in
    "$APP_DIR"/data/maj/*.tar.gz) ;;
    *) echo "Archive refusée : elle doit se trouver dans $APP_DIR/data/maj/." >&2; exit 1 ;;
esac
[ -f "$ARCHIVE" ] || { echo "Archive introuvable : $ARCHIVE" >&2; exit 1; }

if [ "${CONTAR_UPDATE_DETACHED:-}" != "1" ]; then
    systemd-run --unit="contar-maj-$(date +%s)" --collect --quiet \
        --setenv=CONTAR_UPDATE_DETACHED=1 /bin/bash "$0" "$ARCHIVE"
    echo "Mise à jour lancée."
    exit 0
fi

exec >"$LOG" 2>&1
echo "== Mise à jour de Contar, $(date '+%Y-%m-%d %H:%M') =="

WORK=$(mktemp -d /var/tmp/contar-maj.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
tar -xzf "$ARCHIVE" -C "$WORK"
SOURCE=$(dirname "$(find "$WORK" -maxdepth 3 -name install_pi.sh -print -quit)")
if [ -z "$SOURCE" ] || [ ! -f "$SOURCE/run_pi.py" ]; then
    echo "Archive inattendue : install_pi.sh ou run_pi.py introuvable."
    exit 1
fi
echo "Nouvelle version : $(cat "$SOURCE/VERSION" 2>/dev/null || echo '?')"

MODE=gamepad
if grep -q "run_pi.py" /etc/systemd/system/contar.service 2>/dev/null; then
    MODE=gpio
fi
echo "Mode de contrôle conservé : $MODE"

bash "$SOURCE/install_pi.sh" "$SOURCE" "$MODE"
rm -f "$ARCHIVE"
echo "== Mise à jour terminée =="
