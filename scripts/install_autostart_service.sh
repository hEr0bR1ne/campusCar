#!/usr/bin/env bash
# Install/enable the campusCar full-stack boot service for the current user.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/config/robot.env"
UNIT_NAME="campuscar-old-chassis.service"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_FILE="${UNIT_DIR}/${UNIT_NAME}"
START_NOW=0
DISABLE=0
SHOW_STATUS=0

if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
fi

usage() {
    cat <<'EOF'
Usage: ./scripts/install_autostart_service.sh [options]

Options:
  --start-now    Enable and start the service immediately
  --disable      Stop and disable the autostart service
  --status       Show systemd user-service status
  -h, --help     Show this help
EOF
}

log() { printf '[autostart] %s\n' "$*"; }
warn() { printf '[autostart][warn] %s\n' "$*" >&2; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --start-now)
            START_NOW=1
            shift
            ;;
        --disable)
            DISABLE=1
            shift
            ;;
        --status)
            SHOW_STATUS=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            warn "Unknown option: $1"
            usage
            exit 2
            ;;
    esac
done

run_sudo() {
    if [[ -n "${SUDO_PASS:-}" ]]; then
        printf '%s\n' "$SUDO_PASS" | sudo -S -p '' "$@"
    else
        sudo "$@"
    fi
}

systemctl_user() {
    systemctl --user "$@"
}

if [[ "$SHOW_STATUS" -eq 1 ]]; then
    systemctl_user status "$UNIT_NAME" --no-pager || true
    exit 0
fi

if [[ "$DISABLE" -eq 1 ]]; then
    systemctl_user stop "$UNIT_NAME" 2>/dev/null || true
    systemctl_user disable "$UNIT_NAME" 2>/dev/null || true
    systemctl_user daemon-reload 2>/dev/null || true
    log "Autostart disabled: ${UNIT_NAME}"
    exit 0
fi

mkdir -p "$UNIT_DIR"
cat > "$UNIT_FILE" <<EOF
[Unit]
Description=campusCar old chassis full stack and web console
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_ROOT}
Environment=LIVE_RTK_LOGS=0
Environment=START_WEB_GUI=1
Environment=START_CONTROL_GUI=0
Environment=REUSE_CAMERA=1
ExecStart=/usr/bin/env bash -lc 'cd ${PROJECT_ROOT} && exec ./scripts/launch_all.sh'
ExecStop=/usr/bin/env bash -lc 'cd ${PROJECT_ROOT} && ./scripts/stop_all.sh'
Restart=on-failure
RestartSec=8
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=default.target
EOF

chmod 0644 "$UNIT_FILE"
log "Wrote ${UNIT_FILE}"

if command -v loginctl >/dev/null 2>&1; then
    if ! loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q 'Linger=yes'; then
        if run_sudo loginctl enable-linger "$USER" >/dev/null 2>&1; then
            log "Enabled lingering for ${USER}; user service can start after boot without desktop login"
        else
            warn "Could not enable lingering. The service is enabled, but may wait for user login on this machine."
        fi
    fi
fi

systemctl_user daemon-reload
systemctl_user enable "$UNIT_NAME"
log "Autostart enabled: ${UNIT_NAME}"

if [[ "$START_NOW" -eq 1 ]]; then
    systemctl_user restart "$UNIT_NAME"
    log "Service started now"
else
    log "Service will start on next boot. Use --start-now to launch it immediately."
fi

log "Web console URL after startup: http://<NUC_IP>:${WEB_GUI_PORT:-8088}/"
