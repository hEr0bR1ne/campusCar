#!/bin/bash
# ============================================================
# campusCar 全栈停止脚本
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    cat <<'EOF'
Usage: ./scripts/stop_all.sh [--profile NAME]

Stop the campusCar stack using config/profiles/<profile>.env for camera cleanup.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --profile)
            [ $# -ge 2 ] || { echo "--profile requires a value" >&2; exit 2; }
            export ROBOT_PROFILE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

source "${PROJECT_ROOT}/config/robot.env"
SRC_DIR="${PROJECT_ROOT}/src"

echo "========================================"
echo "  campusCar 全栈停止"
echo "========================================"
echo "  Profile: ${ROBOT_PROFILE} (${ROBOT_NAME})"

echo ""
echo "[1/3] 停止 RTK 全栈..."
pkill -f "nmea_serial_driver"  2>/dev/null && echo "✅ nmea_serial_driver 已停止" || true
pkill -f "rosbridge"           2>/dev/null && echo "✅ rosbridge 已停止" || true
pkill -f "rosbridge_bson_tcp.py" 2>/dev/null && echo "✅ rosbridge_bson_tcp 已停止" || true
pkill -f "u2r_r2u_bridge.py"  2>/dev/null && echo "✅ u2r_r2u_bridge 已停止" || true

echo ""
echo "[2/3] 停止视频与相机相关进程..."
pkill -f "rtsp_server.py"      2>/dev/null && echo "✅ rtsp_server 已停止" || true
pkill -f "mjpeg_server.py"     2>/dev/null && echo "✅ mjpeg_server 已停止" || true
pkill -f "mediamtx"            2>/dev/null && echo "✅ mediamtx 已停止" || true
pkill -f "ffmpeg"              2>/dev/null && echo "✅ ffmpeg 已停止" || true
if [ "${#CAMERA_STOP_PATTERNS[@]}" -gt 0 ]; then
    for pattern in "${CAMERA_STOP_PATTERNS[@]}"; do
        [ -n "$pattern" ] && pkill -f "$pattern" 2>/dev/null && echo "✅ 相机进程已停止: $pattern" || true
    done
elif [ -n "${CAMERA_PROCESS_PATTERN:-}" ]; then
    pkill -f "$CAMERA_PROCESS_PATTERN" 2>/dev/null && echo "✅ 相机进程已停止" || true
fi

echo ""
echo "[3/3] 停止控制相关进程..."
pkill -f "car_gui.py"          2>/dev/null && echo "✅ car_gui 已停止" || true
pkill -f "ue_bridge.py"        2>/dev/null && echo "✅ ue_bridge 已停止" || true
pkill -f "keyboard_control.py" 2>/dev/null && echo "✅ keyboard_control 已停止" || true
pkill -f "move.py"             2>/dev/null && echo "✅ move.py 已停止" || true

echo ""
echo "✅ 全栈已停止"
