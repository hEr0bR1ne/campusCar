#!/usr/bin/env bash
# ============================================================
# 小车全栈一键启动
# 包含：ROS2环境 / 相机 / image_flipper / MJPEG推流 / RTK全栈 / 控制GUI
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_ROOT}/config/robot.env"

SRC_DIR="${PROJECT_ROOT}/src"
LOGDIR="${PROJECT_ROOT}/data/logs"
ROS_SETUP="/opt/ros/humble/setup.bash"
TS_BRIDGE_SETUP="${SRC_DIR}/rtk_tools/rosbridge_ts/install/setup.bash"
RTSP_CONFIG="${PROJECT_ROOT}/mediamtx.yml"
RTSP_URL_LOCAL="rtsp://127.0.0.1:${RTSP_PORT}/robot_cam"
RTSP_FFMPEG_LOG="${LOGDIR}/ffmpeg_rtsp.log"
HLS_URL_PATH="/robot_cam/index.m3u8"
HLS_PREVIEW_PATH="/robot_cam/"

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

source "$ROS_SETUP"
[ -f "$HOME/orbbec_ws/install/setup.bash" ] && source "$HOME/orbbec_ws/install/setup.bash"
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
pkill -f image_flipper        2>/dev/null || true
pkill -f mjpeg_server         2>/dev/null || true
pkill -f rtsp_server          2>/dev/null || true
pkill -f mediamtx             2>/dev/null || true
pkill -f "rtsp://127.0.0.1:8554/robot_cam" 2>/dev/null || true
pkill -f car_gui              2>/dev/null || true
pkill -f ue_bridge            2>/dev/null || true
srun fuser -k 9090/tcp
srun fuser -k 8080/tcp
srun fuser -k 8554/tcp
srun fuser -k 8554/udp
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
log "启动 Orbbec 相机..."
nohup ros2 launch orbbec_camera gemini_330_series.launch.py \
    > "$LOGDIR/camera.log" 2>&1 &
log "等待相机就绪..."
for i in $(seq 1 20); do
    sleep 1
    if ros2 topic list 2>/dev/null | grep -q "/camera/color/image_raw"; then
        ok "相机节点在线"
        break
    fi
    if [ "$i" -eq 20 ]; then
        warn "相机话题未出现，检查 $LOGDIR/camera.log"
    fi
done

# ── 6. 启动 image_flipper ────────────────────────────────────
log "启动 image_flipper..."
nohup python3 "$SRC_DIR/rtk_tools/image_flipper.py" \
    > "$LOGDIR/image_flipper.log" 2>&1 &
sleep 1
ok "image_flipper 已启动"

# ── 7. 启动 RTK（串口自动识别）──────────────────────────────
log "启动 RTK 全栈..."
srun systemctl stop ModemManager 2>/dev/null || true
srun systemctl stop brltty       2>/dev/null || true

SERIAL_PORT=""
for p in /dev/serial/by-id/* /dev/ttyACM* /dev/ttyUSB*; do
    [ -e "$p" ] || continue
    srun stty -F "$p" 115200 raw -echo -ixon -ixoff -crtscts 2>/dev/null || continue
    gga=$(srun timeout 1s cat "$p" 2>/dev/null | strings | grep '^\$GNGGA' | head -n1 || true)
    if [ -n "$gga" ]; then SERIAL_PORT="$p"; break; fi
done

if [ -n "$SERIAL_PORT" ]; then
    ok "RTK 串口: $SERIAL_PORT"
    srun chmod 666 "$SERIAL_PORT"
    nohup ros2 run nmea_navsat_driver nmea_serial_driver \
        --ros-args -p port:="$SERIAL_PORT" -p baud:="${RTK_BAUD}" \
        > "$LOGDIR/nmea_navsat_driver.log" 2>&1 &
    sleep 1
    nohup ros2 launch rosbridge_server rosbridge_tcp_launch.xml \
        port:="${ROSBRIDGE_PORT}" bson_only_mode:=True \
        > "$LOGDIR/rosbridge.log" 2>&1 &
    sleep 3
    nohup python3 "$SRC_DIR/rtk_tools/u2r_r2u_bridge.py" \
        --fix-in "${FIX_TOPIC}" --pos-out /R2UTopic_Pos \
        --cmd-in /U2RTopic_Command \
        --logfile "$LOGDIR/u2r_command.log" \
        > "$LOGDIR/ue5_bridge.log" 2>&1 &
    ok "RTK 全栈已启动（rosbridge TCP ${ROSBRIDGE_PORT}）"
else
    warn "未找到 RTK 串口，跳过 RTK 启动"
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

# ── 10. 启动 UE 指令桥接 ─────────────────────────────────────
log "启动 UE 指令桥接..."
nohup python3 "$SRC_DIR/ue_bridge.py" \
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
echo "  UE指令:   ws://${UE_IP:-127.0.0.1}:${ROSBRIDGE_PORT}  →  /U2RTopic_Command"
echo "  日志:     $LOGDIR/"
echo "========================================"
echo ""
wait
