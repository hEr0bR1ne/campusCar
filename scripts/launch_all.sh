#!/usr/bin/env bash
# ============================================================
# 小车全栈一键启动
# 包含：ROS2环境 / 相机 / MJPEG推流 / RTK全栈 / 控制GUI
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_ROOT}/config/robot.env"

SRC_DIR="${PROJECT_ROOT}/src"
LOGDIR="${PROJECT_ROOT}/data/logs"
TS_BRIDGE_SETUP="${ROSBRIDGE_SETUP:-${SRC_DIR}/rtk_tools/rosbridge_ts/install/setup.bash}"
RTSP_CONFIG="${PROJECT_ROOT}/mediamtx.yml"
RTSP_URL_LOCAL="rtsp://127.0.0.1:${RTSP_PORT}/robot_cam"
RTSP_FFMPEG_LOG="${LOGDIR}/ffmpeg_rtsp.log"
RTK_DRIVER_LOG="${LOGDIR}/nmea_navsat_driver.log"
ROSBRIDGE_LOG="${LOGDIR}/rosbridge.log"
RTK_UE_BRIDGE_LOG="${LOGDIR}/ue5_bridge.log"
U2R_COMMAND_LOG="${LOGDIR}/u2r_command.log"
HLS_URL_PATH="/robot_cam/index.m3u8"
HLS_PREVIEW_PATH="/robot_cam/"
LIVE_RTK_LOGS="${LIVE_RTK_LOGS:-1}"
UE_STATUS_INTERVAL="${UE_STATUS_INTERVAL:-1}"
LIVE_LOG_PIDS=()
ORBBEC_LAUNCH_ARGS=(
    "enable_depth:=${ORBBEC_ENABLE_DEPTH:-false}"
    "enable_point_cloud:=${ORBBEC_ENABLE_POINT_CLOUD:-false}"
    "enable_colored_point_cloud:=${ORBBEC_ENABLE_COLORED_POINT_CLOUD:-false}"
    "enable_frame_sync:=${ORBBEC_ENABLE_FRAME_SYNC:-false}"
    "color_width:=${ORBBEC_COLOR_WIDTH:-1280}"
    "color_height:=${ORBBEC_COLOR_HEIGHT:-720}"
    "color_fps:=${ORBBEC_COLOR_FPS:-10}"
    "color_format:=${ORBBEC_COLOR_FORMAT:-MJPG}"
    "color.image_raw.enable_pub_plugins:=[\"image_transport/raw\"]"
)

mkdir -p "$LOGDIR"

srun() { printf '%s\n' "$SUDO_PASS" | sudo -S "$@" 2>/dev/null; }
log()  { echo "[$(date +'%H:%M:%S')] $*"; }
ok()   { echo "[$(date +'%H:%M:%S')] ✅ $*"; }
warn() { echo "[$(date +'%H:%M:%S')] ⚠️  $*"; }
err()  { echo "[$(date +'%H:%M:%S')] ❌ $*"; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || { err "缺少命令: $1"; exit 1; }; }
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
reset_log() { : > "$1"; }
camera_stream_ready() {
    timeout 5s ros2 node list --no-daemon --spin-time 3 2>/dev/null \
        | grep -qx "/camera/camera" || return 1
    timeout 5s ros2 topic info --no-daemon --spin-time 3 /camera/color/image_raw 2>/dev/null \
        | awk '/Publisher count:/ { found=1; if (($3 + 0) > 0) ok=1 } END { exit !(found && ok) }'
}
reset_orbbec_usb() {
    local reset_cmd=""
    if command -v usbreset >/dev/null 2>&1; then
        reset_cmd="$(command -v usbreset)"
    elif [ -x /usr/bin/usbreset ]; then
        reset_cmd="/usr/bin/usbreset"
    else
        return 0
    fi

    if command -v lsusb >/dev/null 2>&1 && lsusb | grep -qi "2bc5:0807"; then
        log "重置 Orbbec USB..."
        "$reset_cmd" 2bc5:0807 >/dev/null 2>&1 \
            || srun "$reset_cmd" 2bc5:0807 >/dev/null 2>&1 \
            || warn "Orbbec USB reset 失败，继续尝试启动相机"
        sleep 2
    fi
}
stop_serial_claimers() {
    # brltty-udev can respawn /sbin/brltty and momentarily grab USB ACM ports.
    srun systemctl stop ModemManager brltty brltty-udev 2>/dev/null || true
    srun pkill -f '^/sbin/brltty' 2>/dev/null || true
    sleep 0.5
}
start_live_log() {
    local label="$1"
    local file="$2"

    [ "$LIVE_RTK_LOGS" = "1" ] || return 0
    touch "$file"
    (
        tail --pid="$$" -n +1 -F "$file" 2>/dev/null \
            | tr '\r' '\n' \
            | awk -v label="$label" 'NF { print "[" strftime("%Y-%m-%d %H:%M:%S") "][" label "] " $0; fflush() }'
    ) &
    LIVE_LOG_PIDS+=("$!")
}
start_live_ue_status() {
    local file="$1"
    local interval="$UE_STATUS_INTERVAL"

    [ "$LIVE_RTK_LOGS" = "1" ] || return 0
    touch "$file"
    (
        local last_line=""
        local line=""
        while true; do
            if [ -s "$file" ]; then
                line="$(awk 'NF { last=$0 } END { print last }' "$file" 2>/dev/null || true)"
                if [ -n "$line" ]; then
                    last_line="$line"
                fi
            fi

            if [ -n "$last_line" ]; then
                printf '[%s][ue-last] %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "$last_line"
            else
                printf '[%s][ue-last] 等待 UE 指令...\n' "$(date +'%Y-%m-%d %H:%M:%S')"
            fi
            sleep "$interval"
        done
    ) &
    LIVE_LOG_PIDS+=("$!")
}
stop_live_logs() {
    local pid
    for pid in "${LIVE_LOG_PIDS[@]}"; do
        pkill -P "$pid" 2>/dev/null || true
        kill "$pid" 2>/dev/null || true
    done
}
trap stop_live_logs EXIT
trap 'stop_live_logs; exit 130' INT
trap 'stop_live_logs; exit 143' TERM

source "$ROS_SETUP"
[ -f "$ORBBEC_SETUP" ] && source "$ORBBEC_SETUP"
[ -f "$TS_BRIDGE_SETUP" ] && source "$TS_BRIDGE_SETUP"

UE_IP="$(pick_ue_ip)"
need_cmd sshpass
need_cmd ffmpeg
need_cmd mediamtx

echo "========================================"
echo "       小车全栈启动"
echo "========================================"

# ── 1. 杀掉旧进程 ────────────────────────────────────────────
log "清理旧进程..."
pkill -f nmea_serial_driver   2>/dev/null || true
pkill -f rosbridge_tcp        2>/dev/null || true
pkill -f rosbridge_websocket  2>/dev/null || true
pkill -f u2r_r2u_bridge.py    2>/dev/null || true
pkill -f orbbec_camera        2>/dev/null || true
pkill -f gemini_330_series.launch.py 2>/dev/null || true
pkill -f "[c]omponent_container.*camera_container" 2>/dev/null || true
pkill -f mjpeg_server         2>/dev/null || true
pkill -f rtsp_server          2>/dev/null || true
pkill -f mediamtx             2>/dev/null || true
pkill -f "rtsp://127.0.0.1:8554/robot_cam" 2>/dev/null || true
pkill -f car_gui              2>/dev/null || true
pkill -f ue_bridge            2>/dev/null || true
pkill -f keyboard_control.py  2>/dev/null || true
srun fuser -k 9090/tcp
srun fuser -k 8080/tcp
srun fuser -k 8554/tcp
srun fuser -k 8554/udp
srun fuser -k 8888/tcp
sleep 1

# ── 2. 检查小车连接 ──────────────────────────────────────────
log "检查小车网络 ($CAR_IP)..."
if ping -c 1 -W 3 "$CAR_IP" > /dev/null 2>&1; then
    ok "小车网络正常"
else
    err "无法 ping 通小车，请检查交换机连接"
    read -p "按 Enter 退出..."
    exit 1
fi

# ── 3. 启动小车底盘节点（远程）───────────────────────────────
log "检查底盘节点..."
if sshpass -p "$CAR_PASS" ssh -o StrictHostKeyChecking=no "$CAR_USER@$CAR_IP" \
    "ros2 node list 2>/dev/null | grep -q base_control" 2>/dev/null; then
    ok "底盘节点已运行"
else
    log "远程启动底盘节点..."
    sshpass -p "$CAR_PASS" ssh -o StrictHostKeyChecking=no "$CAR_USER@$CAR_IP" \
        "nohup bash -lc '${CAR_LAUNCH_CMD}' > ~/ros2_base_control.log 2>&1 &" 2>/dev/null
    sleep 5
    ok "底盘启动命令已发送"
fi

# ── 4. 验证 ROS2 话题 ────────────────────────────────────────
log "验证 ROS2 DDS..."
ros2 daemon stop > /dev/null 2>&1; sleep 1; ros2 daemon start > /dev/null 2>&1; sleep 2
if ros2 topic list 2>/dev/null | grep -q "/cmd_vel"; then
    ok "/cmd_vel 在线"
else
    warn "/cmd_vel 未发现，底盘可能未就绪（继续启动其他服务）"
fi

# ── 5. 启动相机节点 ──────────────────────────────────────────
reset_orbbec_usb
log "启动 Orbbec 相机..."
nohup setsid ros2 launch orbbec_camera gemini_330_series.launch.py \
    "${ORBBEC_LAUNCH_ARGS[@]}" \
    > "$LOGDIR/camera.log" 2>&1 &
CAMERA_LAUNCH_PID=$!
log "等待相机就绪..."
for i in $(seq 1 20); do
    sleep 1
    if camera_stream_ready; then
        ok "相机图像已发布"
        break
    fi
    if ! kill -0 "$CAMERA_LAUNCH_PID" 2>/dev/null; then
        warn "相机启动进程已退出，检查 $LOGDIR/camera.log"
        break
    fi
    if [ "$i" -eq 20 ]; then
        warn "相机图像未发布，检查 $LOGDIR/camera.log"
    fi
done

# ── 6. 启动 RTK（串口自动识别）──────────────────────────────
log "启动 RTK 全栈..."
reset_log "$RTK_DRIVER_LOG"
reset_log "$ROSBRIDGE_LOG"
reset_log "$RTK_UE_BRIDGE_LOG"
reset_log "$U2R_COMMAND_LOG"
if [ "$LIVE_RTK_LOGS" = "1" ]; then
    log "实时显示 RTK/rosbridge/UE 输出（LIVE_RTK_LOGS=0 可关闭）"
    start_live_ue_status "$U2R_COMMAND_LOG"
fi
stop_serial_claimers

SERIAL_PORT=""
for p in /dev/serial/by-id/* /dev/ttyACM* /dev/ttyUSB*; do
    [ -e "$p" ] || continue
    srun stty -F "$p" "${RTK_BAUD}" raw -echo -ixon -ixoff -crtscts 2>/dev/null || continue
    gga=$(srun timeout 1s cat "$p" 2>/dev/null | strings | grep '^\$GNGGA' | head -n1 || true)
    if [ -n "$gga" ]; then SERIAL_PORT="$p"; break; fi
done

if [ -n "$SERIAL_PORT" ]; then
    ok "RTK 串口: $SERIAL_PORT"
    srun chmod 666 "$SERIAL_PORT"
    start_live_log "rtk-driver" "$RTK_DRIVER_LOG"
    nohup setsid ros2 run nmea_navsat_driver nmea_serial_driver \
        --ros-args -p port:="$SERIAL_PORT" -p baud:="${RTK_BAUD}" \
        > "$RTK_DRIVER_LOG" 2>&1 &
    sleep 1
    ok "RTK /fix 数据源已启动"
else
    warn "未找到 RTK 串口，/fix 数据源跳过；rosbridge 和 UE 数据通道仍会启动"
fi

# ── 7. 启动 RTK / UE 数据流 ────────────────────────────────
log "启动 rosbridge WebSocket 数据通道 (${ROSBRIDGE_PORT})..."
if ros2 pkg prefix rosbridge_server >/dev/null 2>&1; then
    start_live_log "rosbridge" "$ROSBRIDGE_LOG"
    nohup ros2 launch rosbridge_server rosbridge_websocket_launch.xml \
        port:="${ROSBRIDGE_PORT}" address:=0.0.0.0 \
        > "$ROSBRIDGE_LOG" 2>&1 &
    sleep 3

    if ss -tln 2>/dev/null | grep -q ":${ROSBRIDGE_PORT}"; then
        ok "rosbridge WebSocket 已监听 ${ROSBRIDGE_PORT}"
    else
        warn "rosbridge WebSocket 未监听，检查 $ROSBRIDGE_LOG"
    fi
else
    warn "未找到 rosbridge_server 包，请先运行 ./scripts/deploy_dependencies.sh"
fi

log "启动 RTK/UE 数据桥..."
start_live_log "rtk-ue" "$RTK_UE_BRIDGE_LOG"
RTK_IMAGE_ARGS=()
if [ -n "${RTK_IMAGE_IN_TOPIC:-}" ]; then
    RTK_IMAGE_ARGS=(--image-in "${RTK_IMAGE_IN_TOPIC}" --image-out "${RTK_IMAGE_TOPIC}")
fi
nohup env \
    PYTHONUNBUFFERED=1 \
    UE_PUBLISH_RATE="${UE_PUBLISH_RATE:-1.0}" \
    RTK_RX_LOG_RATE="${RTK_RX_LOG_RATE:-0}" \
    python3 "$SRC_DIR/rtk_tools/u2r_r2u_bridge.py" \
    --fix-in "${FIX_TOPIC}" \
    --pos-out "${RTK_POS_TOPIC}" \
    --cmd-in "${UE_COMMAND_TOPIC}" \
    --text-out "${RTK_TEXT_TOPIC}" \
    --logfile "$U2R_COMMAND_LOG" \
    "${RTK_IMAGE_ARGS[@]}" \
    > "$RTK_UE_BRIDGE_LOG" 2>&1 &
sleep 1
if pgrep -f "$SRC_DIR/rtk_tools/u2r_r2u_bridge.py" > /dev/null; then
    ok "RTK/UE 数据流已启动：${FIX_TOPIC} → ${RTK_POS_TOPIC}，${UE_COMMAND_TOPIC} → 日志"
else
    warn "RTK/UE 数据桥启动失败，检查 $RTK_UE_BRIDGE_LOG"
fi

# ── 8. 启动 RTSP 推流 ───────────────────────────────────────
if [ ! -f "$RTSP_CONFIG" ]; then
    err "RTSP 配置文件不存在: $RTSP_CONFIG"
    exit 1
fi

log "启动 mediamtx RTSP 服务器..."
rm -f "$LOGDIR/mediamtx.log" "$RTSP_FFMPEG_LOG"
nohup mediamtx "$RTSP_CONFIG" > "$LOGDIR/mediamtx.log" 2>&1 &
sleep 1
if grep -q "using an empty configuration" "$LOGDIR/mediamtx.log" 2>/dev/null; then
    err "mediamtx 未加载 $RTSP_CONFIG"
    exit 1
fi
if ! ss -tln 2>/dev/null | grep -q ":${RTSP_PORT}"; then
    err "RTSP 端口 ${RTSP_PORT} 未监听，检查 $LOGDIR/mediamtx.log"
    exit 1
fi
log "启动 RTSP 推流 (${RTSP_PORT})..."
nohup python3 "$SRC_DIR/rtsp_server.py" \
    --rtsp "$RTSP_URL_LOCAL" \
    --ffmpeg-log "$RTSP_FFMPEG_LOG" \
    > "$LOGDIR/rtsp_server.log" 2>&1 &
sleep 1
if pgrep -f "$SRC_DIR/rtsp_server.py" > /dev/null; then
    ok "RTSP 推流节点已启动"
else
    err "RTSP 推流节点启动失败，检查 $LOGDIR/rtsp_server.log"
    exit 1
fi
ok "RTSP 地址 → rtsp://${UE_IP:-127.0.0.1}:${RTSP_PORT}/robot_cam"
ok "UE(HLS) → http://${UE_IP:-127.0.0.1}:${HLS_PORT}${HLS_URL_PATH}"
ok "HLS预览 → http://${UE_IP:-127.0.0.1}:${HLS_PORT}${HLS_PREVIEW_PATH}"

# ── 9. 启动 MJPEG 浏览器预览 ────────────────────────────────
log "启动 MJPEG 浏览器预览 (${MJPEG_PORT})..."
nohup python3 "$SRC_DIR/mjpeg_server.py" \
    --topic "${IMAGE_TOPIC}" \
    --port "${MJPEG_PORT}" \
    > "$LOGDIR/mjpeg_server.log" 2>&1 &
sleep 1
if pgrep -f "$SRC_DIR/mjpeg_server.py" > /dev/null; then
    ok "浏览器预览地址 → http://${UE_IP:-127.0.0.1}:${MJPEG_PORT}/"
else
    err "MJPEG 预览服务启动失败，检查 $LOGDIR/mjpeg_server.log"
    exit 1
fi

# ── 10. 启动 UE 指令桥接 ────────────────────────────────────
log "启动 UE 指令桥接..."
nohup env \
    PYTHONUNBUFFERED=1 \
    CMD_VEL_TOPIC="${CMD_VEL_TOPIC}" \
    FIX_TOPIC="${FIX_TOPIC}" \
    HEADING_TOPIC="${HEADING_TOPIC}" \
    UE_COMMAND_TOPIC="${UE_COMMAND_TOPIC}" \
    RTK_TEXT_TOPIC="${RTK_TEXT_TOPIC}" \
    MAX_LINEAR_SPEED="${MAX_LINEAR_SPEED:-1.0}" \
    MAX_ANGULAR_SPEED="${MAX_ANGULAR_SPEED:-1.0}" \
    UE_DIRECTION_RATE_HZ="${UE_DIRECTION_RATE_HZ:-10}" \
    UE_DIRECTION_TIMEOUT_SEC="${UE_DIRECTION_TIMEOUT_SEC:-0.8}" \
    UE_NAV_RATE_HZ="${UE_NAV_RATE_HZ:-10}" \
    UE_ARRIVE_THRESHOLD_M="${UE_ARRIVE_THRESHOLD_M:-0.5}" \
    UE_HEADING_KP="${UE_HEADING_KP:-1.2}" \
    UE_HEADING_TOLERANCE="${UE_HEADING_TOLERANCE:-0.15}" \
    UE_COORD_MODE="${UE_COORD_MODE:-auto}" \
    UE_LOCAL_ORIGIN_LAT="${UE_LOCAL_ORIGIN_LAT:-}" \
    UE_LOCAL_ORIGIN_LON="${UE_LOCAL_ORIGIN_LON:-}" \
    UE_LOCAL_ORIGIN_X="${UE_LOCAL_ORIGIN_X:-0}" \
    UE_LOCAL_ORIGIN_Y="${UE_LOCAL_ORIGIN_Y:-0}" \
    UE_UNITS_PER_METER="${UE_UNITS_PER_METER:-100}" \
    UE_LOCAL_ROTATION_DEG="${UE_LOCAL_ROTATION_DEG:-0}" \
    UE_LOCAL_X_SIGN="${UE_LOCAL_X_SIGN:-1}" \
    UE_LOCAL_Y_SIGN="${UE_LOCAL_Y_SIGN:-1}" \
    python3 "$SRC_DIR/ue_bridge.py" \
    > "$LOGDIR/ue_bridge.log" 2>&1 &
sleep 1
if pgrep -f "$SRC_DIR/ue_bridge.py" > /dev/null; then
    ok "UE 指令桥接已启动"
else
    err "UE 指令桥接启动失败，检查 $LOGDIR/ue_bridge.log"
fi

# ── 11. 启动控制 GUI ─────────────────────────────────────────
log "启动控制 GUI..."
sleep 1
python3 "$SRC_DIR/car_gui.py" &

echo ""
echo "========================================"
echo "  全栈启动完成"
echo "  GPS/UE5:  ${UE_IP:-127.0.0.1}:${ROSBRIDGE_PORT}"
echo "  视频流:   rtsp://${UE_IP:-127.0.0.1}:${RTSP_PORT}/robot_cam"
echo "  UE(HLS):  http://${UE_IP:-127.0.0.1}:${HLS_PORT}${HLS_URL_PATH}"
echo "  HLS页:    http://${UE_IP:-127.0.0.1}:${HLS_PORT}${HLS_PREVIEW_PATH}"
echo "  浏览器:   http://${UE_IP:-127.0.0.1}:${MJPEG_PORT}/"
echo "  RTK位置:  ${RTK_POS_TOPIC} (${UE_PUBLISH_RATE:-1.0}Hz)"
echo "  UE指令:   ws://${UE_IP:-127.0.0.1}:${ROSBRIDGE_PORT}  →  ${UE_COMMAND_TOPIC}"
echo "  RTK串口:  ${SERIAL_PORT:-未检测到}"
if [ "$LIVE_RTK_LOGS" = "1" ]; then
    echo "  实时日志:  已显示 RTK/rosbridge 输出"
else
    echo "  实时日志:  已关闭（日志仍写入 $LOGDIR）"
fi
echo "  日志:     $LOGDIR/"
echo "========================================"
echo ""
wait
