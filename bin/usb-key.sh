#!/bin/bash
# Contar — clé USB d'import (v0.9).
#
# Lancé par l'application (utilisateur « contar ») avec sudo, pour les deux
# seules choses qu'elle n'a pas le droit de faire elle-même :
#
#   usb-key.sh mount /dev/sda1     relie la clé au dossier /run/contar/cle
#   usb-key.sh umount              la détache
#
# La clé est TOUJOURS reliée en lecture seule : la boîte n'y écrit jamais,
# et la retirer à n'importe quel moment ne peut pas l'abîmer.
#
# Par prudence, ce script refuse tout ce qui n'est pas une clé ou un disque
# branché en USB (jamais la carte mémoire de la boîte).

set -u

MOUNT_DIR="${CONTAR_USB_MOUNT_DIR:-/run/contar/cle}"
APP_USER="${CONTAR_APP_USER:-contar}"

fail() {
    echo "usb-key: $1" >&2
    exit "${2:-1}"
}

do_umount() {
    if mountpoint -q "$MOUNT_DIR" 2>/dev/null; then
        umount "$MOUNT_DIR" 2>/dev/null || umount -l "$MOUNT_DIR" 2>/dev/null || true
    fi
    return 0
}

do_mount() {
    local dev="$1"
    [[ "$dev" =~ ^/dev/sd[a-z]+[0-9]*$ ]] || fail "périphérique refusé : $dev" 2
    [ -b "$dev" ] || fail "périphérique absent : $dev" 3

    # Le disque qui porte cette partition doit être branché en USB.
    local disk tran
    disk="$(lsblk -no PKNAME "$dev" 2>/dev/null | head -n 1)"
    [ -n "$disk" ] || disk="$(basename "$dev")"
    tran="$(lsblk -dno TRAN "/dev/$disk" 2>/dev/null | tr -d '[:space:]')"
    [ "$tran" = "usb" ] || fail "ce n'est pas une clé USB : $dev" 2

    # Jamais le disque sur lequel tourne la boîte (Pi démarré sur un disque USB).
    if lsblk -nro MOUNTPOINT "/dev/$disk" 2>/dev/null | grep -E '^(/|/boot.*)$' >/dev/null; then
        fail "ce disque est celui de la boîte : $dev" 2
    fi

    do_umount
    mkdir -p "$MOUNT_DIR"

    local fstype uid gid
    fstype="$(lsblk -dno FSTYPE "$dev" 2>/dev/null | tr -d '[:space:]')"
    uid="$(id -u "$APP_USER" 2>/dev/null || echo 0)"
    gid="$(id -g "$APP_USER" 2>/dev/null || echo 0)"

    local common="ro,nosuid,nodev,noexec"
    case "$fstype" in
        vfat)
            mount -t vfat -o "$common,uid=$uid,gid=$gid,utf8=1,shortname=mixed" "$dev" "$MOUNT_DIR" ;;
        exfat)
            mount -t exfat -o "$common,uid=$uid,gid=$gid" "$dev" "$MOUNT_DIR" ;;
        ntfs)
            mount -t ntfs3 -o "$common,uid=$uid,gid=$gid" "$dev" "$MOUNT_DIR" 2>/dev/null \
                || mount -t ntfs -o "$common,uid=$uid,gid=$gid" "$dev" "$MOUNT_DIR" ;;
        ext2|ext3|ext4)
            mount -t "$fstype" -o "$common,noload" "$dev" "$MOUNT_DIR" 2>/dev/null \
                || mount -t "$fstype" -o "$common" "$dev" "$MOUNT_DIR" ;;
        *)
            mount -o "$common" "$dev" "$MOUNT_DIR" ;;
    esac || fail "clé illisible ($dev, format ${fstype:-inconnu})" 4

    echo "$MOUNT_DIR"
}

case "${1:-}" in
    mount)
        [ $# -eq 2 ] || fail "usage : usb-key.sh mount /dev/sdX1" 64
        do_mount "$2"
        ;;
    umount)
        do_umount
        ;;
    *)
        fail "usage : usb-key.sh mount /dev/sdX1 | umount" 64
        ;;
esac
