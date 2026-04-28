#!/bin/bash
# ============================================================
# campusCar 全栈状态检查脚本
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    cat <<'EOF'
Usage: ./scripts/check_all.sh [--profile NAME]

Check the full stack using config/profiles/<profile>.env.
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
LOGDIR="${PROJECT_ROOT}/data/logs"

[ -f "$ROS_SETUP" ] && source "$ROS_SETUP"
for setup_file in "${CAMERA_SETUP_FILES[@]}"; do
    [ -f "$setup_file" ] && source "$setup_file"
done
[ -f "$ROSBRIDGE_SETUP" ] && source "$ROSBRIDGE_SETUP"

pick_ue_ip() {
    local ip
    ip=$(ip -o -4 addr show scope global 2>/dev/null | awk '$2 ~ /^(wl|wlan)/ {split($4, a, "/"); print a[1]; exit}')
    if [ -n "$ip" ]; then
        printf '%s\n' "$ip"
        return
    fi
    ip=$(ip -o -4 addr show scope global 2>/dev/null | awk '$2 != "lo" {split($4, a, "/"); print a[1]; exit}')
    printf '%s\n' "$ip"
}

UE_IP="$(pick_ue_ip)"
HLS_URL_PATH="/robot_cam/index.m3u8"
HLS_PREVIEW_PATH="/robot_cam/"

echo "========================================"
echo "  campusCar 全栈状态检查"
echo "========================================"
echo "  Profile: ${ROBOT_PROFILE} (${ROBOT_NAME})"
echo "  Chassis: ${CHASSIS_ADAPTER} / ${CHASSIS_START_MODE}"
echo "  Camera:  ${CAMERA_ADAPTER} / ${CAMERA_START_MODE}"

# 1. 网络
echo ""
echo "【网络】"
if [ -z "${CAR_IP:-}" ] || [ "${CHASSIS_REQUIRED:-0}" = "0" ]; then
    echo "ℹ️ 底盘网络检查跳过"
elif ping -c 1 -W 2 "$CAR_IP" > /dev/null 2>&1; then
    echo "✅ 底盘 ($CAR_IP): ping OK"
else
    echo "❌ 底盘 ($CAR_IP): 不可达"
fi

# 2. ROS2 话题
echo ""
echo "【ROS2 话题】"
TOPICS=$(ros2 topic list 2>/dev/null)
for t in "${CMD_VEL_TOPIC}" /odom /imu /battery "${FIX_TOPIC}" "${RTK_POS_TOPIC}" "${RTK_TEXT_TOPIC}" "${UE_COMMAND_TOPIC}" "${IMAGE_TOPIC}"; do
    if echo "$TOPICS" | grep -q "$t"; then
        echo "✅ $t"
    else
        echo "❌ $t (未发现)"
    fi
done

# 3. rosbridge 端口
echo ""
echo "【rosbridge TCP/BSON ${ROSBRIDGE_PORT}】"
if ss -tlnp 2>/dev/null | grep -q ":${ROSBRIDGE_PORT}"; then
    echo "✅ 端口 ${ROSBRIDGE_PORT} 监听中"
    [ -n "$UE_IP" ] && echo "   UE5 连接地址: $UE_IP:${ROSBRIDGE_PORT}"
else
    echo "❌ 端口 ${ROSBRIDGE_PORT} 未监听 (RTK 未启动)"
fi

# 4. RTSP 视频流
echo ""
echo "【RTSP 视频流】"
if ss -tlnp 2>/dev/null | grep -q ":${RTSP_PORT}"; then
    echo "✅ 端口 ${RTSP_PORT} 监听中"
    [ -n "$UE_IP" ] && echo "   视频流地址: rtsp://$UE_IP:${RTSP_PORT}/robot_cam"
else
    echo "❌ 端口 ${RTSP_PORT} 未监听"
fi
pgrep -a -f "mediamtx"     | head -1 && echo "✅ mediamtx"     || echo "❌ mediamtx 未运行"
pgrep -a -f "rtsp_server"  | head -1 && echo "✅ rtsp_server"  || echo "❌ rtsp_server 未运行"

# 5. HLS（UE 推荐）
echo ""
echo "【HLS（UE 推荐）】"
if ss -tlnp 2>/dev/null | grep -q ":${HLS_PORT}"; then
    echo "✅ 端口 ${HLS_PORT} 监听中"
    [ -n "$UE_IP" ] && echo "   HLS地址: http://$UE_IP:${HLS_PORT}/robot_cam/index.m3u8"
    [ -n "$UE_IP" ] && echo "   HLS预览: http://$UE_IP:${HLS_PORT}/robot_cam/"
else
    echo "❌ 端口 ${HLS_PORT} 未监听"
fi

# 6. 浏览器预览
echo ""
echo "【浏览器预览】"
if ss -tlnp 2>/dev/null | grep -q ":${MJPEG_PORT}"; then
    echo "✅ 端口 ${MJPEG_PORT} 监听中"
    [ -n "$UE_IP" ] && echo "   预览地址: http://$UE_IP:${MJPEG_PORT}/"
else
    echo "❌ 端口 ${MJPEG_PORT} 未监听"
fi
pgrep -a -f "mjpeg_server" | head -1 && echo "✅ mjpeg_server" || echo "❌ mjpeg_server 未运行"

echo ""
echo "【相机驱动】"
if [ "${CAMERA_DEPENDENCY_MODE:-none}" = "hikrobot_aravis" ]; then
    ros2 pkg prefix camera_aravis2 >/dev/null 2>&1 && echo "✅ camera_aravis2 已安装" || echo "❌ camera_aravis2 未安装"
    command -v arv-tool-0.8 >/dev/null 2>&1 && echo "✅ arv-tool-0.8 已安装" || echo "❌ arv-tool-0.8 未安装"
fi
CAMERA_PGREP_FILE="/tmp/campuscar_camera_pgrep.$$"
if [ -n "${CAMERA_PROCESS_PATTERN:-}" ]; then
    if pgrep -a -f "$CAMERA_PROCESS_PATTERN" > "$CAMERA_PGREP_FILE" 2>/dev/null; then
        head -1 "$CAMERA_PGREP_FILE"
        echo "✅ ${CAMERA_DRIVER_LABEL}"
    else
        echo "❌ ${CAMERA_DRIVER_LABEL} 未运行"
    fi
elif [ "${CAMERA_START_MODE:-skip}" = "skip" ]; then
    echo "ℹ️ 当前 profile 未配置自动相机驱动"
else
    echo "❌ ${CAMERA_DRIVER_LABEL} 未运行"
fi
rm -f "$CAMERA_PGREP_FILE"

# 7. RTK 进程
echo ""
echo "【RTK 进程】"
pgrep -a -f "nmea_serial_driver" | head -1 && echo "✅ nmea_serial_driver" || echo "❌ nmea_serial_driver 未运行"
pgrep -a -f "rosbridge" | head -1 | awk '{print $1}' > /dev/null && \
    pgrep -f "rosbridge" > /dev/null && echo "✅ rosbridge" || echo "❌ rosbridge 未运行"
pgrep -f "u2r_r2u_bridge" > /dev/null && echo "✅ u2r_r2u_bridge" || echo "❌ u2r_r2u_bridge 未运行"

# 8. 控制进程
echo ""
echo "【控制进程】"
pgrep -a -f "ue_bridge.py" | head -1 && echo "✅ ue_bridge" || echo "❌ ue_bridge 未运行"
pgrep -a -f "keyboard_control.py" | head -1 && echo "✅ keyboard_control" || echo "ℹ️ keyboard_control 未运行（按需启动）"

echo ""
echo "========================================"
