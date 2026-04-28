#!/usr/bin/env bash
# Bind unbound CH340 USB serial adapters so /dev/ttyUSB* nodes appear.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set +u
# shellcheck disable=SC1091
[ -f "${PROJECT_ROOT}/config/robot.local.env" ] && source "${PROJECT_ROOT}/config/robot.local.env" >/dev/null 2>&1 || true
set -u

sudo_run() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif [ -n "${SUDO_PASS:-}" ]; then
        printf '%s\n' "$SUDO_PASS" | sudo -S "$@"
    else
        sudo -n "$@"
    fi
}

if command -v lsmod >/dev/null 2>&1 && ! lsmod | grep -q '^ch341 '; then
    sudo_run modprobe ch341 >/dev/null 2>&1 || true
elif [ -r /proc/modules ] && ! grep -q '^ch341 ' /proc/modules; then
    sudo_run modprobe ch341 >/dev/null 2>&1 || true
fi

for iface in /sys/bus/usb/devices/*:1.*; do
    [ -e "$iface" ] || continue
    dev="${iface%:*}"
    [ -f "$dev/idVendor" ] && [ -f "$dev/idProduct" ] || continue
    vendor="$(cat "$dev/idVendor")"
    product="$(cat "$dev/idProduct")"

    case "${vendor}:${product}" in
        1a86:7523|1a86:7522|1a86:5523|4348:5523|2184:0057|9986:7523)
            ;;
        *)
            continue
            ;;
    esac

    [ ! -e "$iface/driver" ] || continue
    iface_name="$(basename "$iface")"
    echo "绑定 CH340 串口接口: ${iface_name}"
    sudo_run sh -c "printf '%s\n' '$iface_name' > /sys/bus/usb/drivers/ch341/bind" >/dev/null 2>&1 || true
done
