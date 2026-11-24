#!/bin/bash
# usb-gadget.sh — la boîte vue par un ordinateur relié au port USB-C (v0.11).
#
# Le port USB-C du Raspberry Pi 4 sait se présenter comme un périphérique
# (pilote dwc2, « dtoverlay=dwc2,dr_mode=peripheral » dans config.txt). On y
# déclare un périphérique composite :
#   - une carte réseau USB : l'ordinateur reçoit une adresse et ouvre
#     l'administration sur http://10.55.0.1 (ou http://contar.local) ;
#     deux variantes, l'ordinateur choisit celle qu'il connaît :
#       configuration 1 : RNDIS (Windows, pilote installé tout seul)
#       configuration 2 : CDC-ECM (macOS, Linux)
#   - un petit disque « CONTAR » (dépôt) : on y copie des histoires et des
#     musiques ; après l'éjection, la boîte les range dans sa bibliothèque
#     (voir app/usb_gadget.py et app/depot_import.py).
#
#   usb-gadget.sh setup            crée le périphérique (au démarrage, service
#                                  contar-usb-gadget) et relie le dépôt
#   usb-gadget.sh state            état du port : configured = relié à un ordinateur
#   usb-gadget.sh storage-attach   remet le disque de dépôt à disposition de l'ordinateur
#   usb-gadget.sh storage-detach   le reprend (l'ordinateur le voit disparaître)
#   usb-gadget.sh storage-state    attached / detached
#   usb-gadget.sh depot-mount      monte le dépôt pour la boîte (après détachement)
#   usb-gadget.sh depot-umount     le démonte
#   usb-gadget.sh depot-reset      le vide (nouveau disque, avec ses dossiers et son mode d'emploi)
#   usb-gadget.sh throttled        sortie brute de « vcgencmd get_throttled »
#
# Appelé par app/usb_gadget.py via sudo (règle sudoers posée par
# install_pi.sh : ce script seul, rien d'autre).

set -euo pipefail

# Réglages posés par install_pi.sh (taille du dépôt…) : sudo ne transmet pas
# l'environnement du service, on les relit ici.
if [ -r /etc/default/contar ]; then
    # shellcheck disable=SC1091
    . /etc/default/contar
fi

APP_DIR="${CONTAR_APP_DIR:-/opt/contar}"
APP_USER="${CONTAR_APP_USER:-contar}"
IMAGE="${CONTAR_DEPOT_IMAGE:-$APP_DIR/data/depot.img}"
SIZE_MB="${CONTAR_DEPOT_MB:-4096}"
MOUNT_DIR="/run/contar/depot"
G="/sys/kernel/config/usb_gadget/contar"
LUN="$G/functions/mass_storage.0/lun.0"
TEMPLATE="$APP_DIR/app/assets/depot"

udc_name() { ls /sys/class/udc 2>/dev/null | head -n 1; }

mac_from() {
    # Adresse MAC « locale » stable, tirée du numéro de série du Pi.
    local prefix="$1" serial
    serial=$(awk '/Serial/ {print $3}' /proc/cpuinfo 2>/dev/null | tail -c 9)
    serial=${serial:-12345678}
    printf '%s:%s:%s:%s:%s\n' "$prefix" "${serial:0:2}" "${serial:2:2}" "${serial:4:2}" "${serial:6:2}"
}

make_image() {
    mkdir -p "$(dirname "$IMAGE")"
    rm -f "$IMAGE"
    truncate -s "${SIZE_MB}M" "$IMAGE"          # fichier creux : la place n'est prise qu'à l'usage
    mkfs.vfat -F 32 -n CONTAR "$IMAGE" >/dev/null
    if [ -d "$TEMPLATE" ]; then
        local tmp
        tmp=$(mktemp -d)
        mount -o loop "$IMAGE" "$tmp"
        cp -r "$TEMPLATE"/. "$tmp"/
        sync
        umount "$tmp"
        rmdir "$tmp"
    fi
    chown "$APP_USER":"$APP_USER" "$IMAGE"
}

storage_attach() {
    [ -f "$IMAGE" ] || make_image
    if mountpoint -q "$MOUNT_DIR"; then
        echo "Le dépôt est monté sur la boîte : démontez-le d'abord." >&2
        exit 1
    fi
    [ -e "$LUN/file" ] && echo "$IMAGE" > "$LUN/file"
}

storage_detach() {
    if [ -e "$LUN/file" ]; then
        # Si l'ordinateur tient encore le disque, on force l'éjection.
        echo 1 > "$LUN/forced_eject" 2>/dev/null || echo "" > "$LUN/file"
    fi
}

setup() {
    modprobe libcomposite
    mountpoint -q /sys/kernel/config || mount -t configfs none /sys/kernel/config
    if [ -d "$G" ] && [ -n "$(cat "$G/UDC" 2>/dev/null)" ]; then
        network_up
        echo "Périphérique USB déjà en place."
        return
    fi
    mkdir -p "$G"
    cd "$G"
    echo 0x1d6b > idVendor          # Linux Foundation
    echo 0x0104 > idProduct         # Multifunction Composite Gadget
    echo 0x0110 > bcdDevice
    echo 0x0200 > bcdUSB
    echo 0xEF > bDeviceClass        # périphérique composite (IAD)
    echo 0x02 > bDeviceSubClass
    echo 0x01 > bDeviceProtocol
    mkdir -p strings/0x409
    awk '/Serial/ {print $3}' /proc/cpuinfo > strings/0x409/serialnumber 2>/dev/null || true
    echo "Audiolibre" > strings/0x409/manufacturer
    echo "Contar" > strings/0x409/product

    # Windows : descripteurs qui lui font choisir son pilote RNDIS tout seul.
    echo 1 > os_desc/use
    echo 0xcd > os_desc/b_vendor_code
    echo MSFT100 > os_desc/qw_sign

    mkdir -p functions/rndis.usb0
    mac_from 02:1c > functions/rndis.usb0/dev_addr
    mac_from 02:1d > functions/rndis.usb0/host_addr
    echo RNDIS > functions/rndis.usb0/os_desc/interface.rndis/compatible_id
    echo 5162001 > functions/rndis.usb0/os_desc/interface.rndis/sub_compatible_id

    mkdir -p functions/ecm.usb0
    mac_from 02:1e > functions/ecm.usb0/dev_addr
    mac_from 02:1f > functions/ecm.usb0/host_addr

    mkdir -p functions/mass_storage.0
    echo 1 > functions/mass_storage.0/stall
    echo 1 > "$LUN/removable"
    echo 0 > "$LUN/ro"
    echo 0 > "$LUN/cdrom"
    echo 1 > "$LUN/nofua"
    echo "CONTAR depot" > "$LUN/inquiry_string" 2>/dev/null || true

    for C in 1 2; do
        mkdir -p "configs/c.$C/strings/0x409"
        echo 500 > "configs/c.$C/MaxPower"
        echo 0x80 > "configs/c.$C/bmAttributes"
    done
    echo "RNDIS + dépôt" > configs/c.1/strings/0x409/configuration
    echo "ECM + dépôt" > configs/c.2/strings/0x409/configuration
    ln -s functions/rndis.usb0 configs/c.1/
    ln -s functions/mass_storage.0 configs/c.1/
    ln -s functions/ecm.usb0 configs/c.2/
    ln -s functions/mass_storage.0 configs/c.2/
    ln -s configs/c.1 os_desc/

    local udc
    udc=$(udc_name)
    if [ -z "$udc" ]; then
        echo "Aucun contrôleur USB-C en mode périphérique (dtoverlay=dwc2,dr_mode=peripheral manquant ? redémarrage nécessaire ?)." >&2
        exit 1
    fi
    echo "$udc" > UDC
    network_up
    storage_attach
    echo "Périphérique USB prêt ($udc)."
}

network_up() {
    # Un pont réunit les deux cartes réseau possibles (RNDIS = usb0,
    # ECM = usb1) : la boîte a toujours la même adresse, 10.55.0.1, quel que
    # soit le système de l'ordinateur. Le serveur DHCP (contar-usb-dhcp)
    # écoute sur ce pont.
    ip link show br-contar >/dev/null 2>&1 || ip link add br-contar type bridge
    local ifname
    for f in rndis.usb0 ecm.usb0; do
        ifname=$(cat "$G/functions/$f/ifname" 2>/dev/null || true)
        if [ -n "$ifname" ] && ip link show "$ifname" >/dev/null 2>&1; then
            ip link set "$ifname" master br-contar
            ip link set "$ifname" up
        fi
    done
    ip addr replace 10.55.0.1/29 dev br-contar
    ip link set br-contar up
}

case "${1:-}" in
    setup) setup ;;
    state)
        udc=$(udc_name)
        if [ -n "$udc" ]; then cat "/sys/class/udc/$udc/state"; else echo "absent"; fi
        ;;
    storage-attach) storage_attach ;;
    storage-detach) storage_detach ;;
    storage-state)
        if [ -n "$(cat "$LUN/file" 2>/dev/null)" ]; then echo attached; else echo detached; fi
        ;;
    depot-mount)
        [ -f "$IMAGE" ] || make_image
        if [ -n "$(cat "$LUN/file" 2>/dev/null)" ]; then
            echo "Le dépôt est encore relié à l'ordinateur." >&2
            exit 1
        fi
        mkdir -p "$MOUNT_DIR"
        mountpoint -q "$MOUNT_DIR" || {
            fsck.vfat -a "$IMAGE" >/dev/null 2>&1 || true   # débranché sans éjecter
            uid=$(id -u "$APP_USER"); gid=$(id -g "$APP_USER")
            mount -o loop,uid="$uid",gid="$gid",umask=022,utf8 "$IMAGE" "$MOUNT_DIR"
        }
        echo "$MOUNT_DIR"
        ;;
    depot-umount)
        if mountpoint -q "$MOUNT_DIR"; then sync; umount "$MOUNT_DIR"; fi
        ;;
    depot-reset)
        if mountpoint -q "$MOUNT_DIR"; then sync; umount "$MOUNT_DIR"; fi
        make_image
        ;;
    throttled) vcgencmd get_throttled 2>/dev/null || echo "throttled=?" ;;
    *)
        echo "Usage : usb-gadget.sh setup|state|storage-attach|storage-detach|storage-state|depot-mount|depot-umount|depot-reset|throttled" >&2
        exit 2
        ;;
esac
