#!/usr/bin/env bash
# ============================================================
# 小车全栈一键启动
# 包含：ROS2环境 / 相机 / MJPEG推流 / RTK全栈 / 控制GUI
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    cat <<'EOF'
Usage: ./scripts/launch_all.sh [--profile NAME]

Start the full campusCar stack. Hardware-specific chassis/camera settings are
loaded from config/profiles/<profile>.env.

Options:
  --profile NAME   Robot hardware profile, default: campus_car
  -h, --help       Show this help
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
REUSE_CAMERA="${REUSE_CAMERA:-1}"
CAMERA_REUSE_PROBE_TIMEOUT="${CAMERA_REUSE_PROBE_TIMEOUT:-3}"
START_GUI_EARLY="${START_GUI_EARLY:-1}"
REFRESH_ROS_DAEMON="${REFRESH_ROS_DAEMON:-0}"
LIVE_LOG_PIDS=()
GUI_STARTED=0
CAMERA_REUSE_READY=0

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
camera_frame_ready() {
    local timeout_s="${1:-8}"
    timeout "${timeout_s}s" python3 - "${IMAGE_TOPIC}" "$timeout_s" >/dev/null 2>&1 <<'PY'
import sys
import time
import os

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

topic = sys.argv[1]
deadline = time.monotonic() + float(sys.argv[2])

class CameraProbe(Node):
    def __init__(self):
        super().__init__("camera_frame_probe")
        self.create_subscription(Image, topic, self._on_image, qos_profile_sensor_data)

    def _on_image(self, _msg):
        os._exit(0)

rclpy.init(args=None)
node = CameraProbe()
while rclpy.ok() and time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=0.2)
os._exit(1)
PY
}
camera_process_alive() {
    [ -n "${CAMERA_PROCESS_PATTERN:-}" ] || return 1
    pgrep -f "$CAMERA_PROCESS_PATTERN" >/dev/null 2>&1
}
mjpeg_frame_ready() {
    local timeout_s="${1:-1}"
    local url="${MJPEG_STREAM_URL:-http://127.0.0.1:${MJPEG_PORT}/stream}"
    timeout "${timeout_s}s" python3 - "$url" "$timeout_s" >/dev/null 2>&1 <<'PY'
import sys
import time
from urllib.request import Request, urlopen

url = sys.argv[1]
deadline = time.monotonic() + float(sys.argv[2])
buf = b""

try:
    req = Request(url, headers={"User-Agent": "campusCar-launch-probe"})
    with urlopen(req, timeout=float(sys.argv[2])) as stream:
        while time.monotonic() < deadline:
            chunk = stream.read(4096)
            if not chunk:
                break
            buf += chunk
            start = buf.find(b"\xff\xd8")
            end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
            if start >= 0 and end > start:
                sys.exit(0)
            if len(buf) > 1024 * 1024:
                buf = buf[-1024 * 1024:]
except Exception:
    pass
sys.exit(1)
PY
}
reset_camera_usb() {
    [ "$RESET_CAMERA_USB" = "1" ] || return 0
    [ -n "${CAMERA_USB_RESET_IDS:-}" ] || return 0

    local reset_cmd=""
    if command -v usbreset >/dev/null 2>&1; then
        reset_cmd="$(command -v usbreset)"
    elif [ -x /usr/bin/usbreset ]; then
        reset_cmd="/usr/bin/usbreset"
    else
        return 0
    fi

    local usb_id
    for usb_id in $CAMERA_USB_RESET_IDS; do
        if command -v lsusb >/dev/null 2>&1 && lsusb | grep -qi "$usb_id"; then
            log "重置 ${CAMERA_DRIVER_LABEL} USB (${usb_id})..."
            "$reset_cmd" "$usb_id" >/dev/null 2>&1 \
                || srun "$reset_cmd" "$usb_id" >/dev/null 2>&1 \
                || warn "${CAMERA_DRIVER_LABEL} USB reset 失败，继续尝试启动相机"
            sleep 2
        fi
    done
}
source_setup_files() {
    local setup_file
    [ -f "$ROS_SETUP" ] && source "$ROS_SETUP"
    for setup_file in "${CAMERA_SETUP_FILES[@]}"; do
        [ -f "$setup_file" ] && source "$setup_file"
    done
    [ -f "$TS_BRIDGE_SETUP" ] && source "$TS_BRIDGE_SETUP"
}
stop_camera_processes() {
    local pattern
    if [ "${#CAMERA_STOP_PATTERNS[@]}" -gt 0 ]; then
        for pattern in "${CAMERA_STOP_PATTERNS[@]}"; do
            [ -n "$pattern" ] && pkill -f "$pattern" 2>/dev/null || true
        done
    elif [ -n "${CAMERA_PROCESS_PATTERN:-}" ]; then
        pkill -f "$CAMERA_PROCESS_PATTERN" 2>/dev/null || true
    fi
}
check_chassis_network() {
    if [ "${CHASSIS_START_MODE:-skip}" = "skip" ] || [ "${CHASSIS_REQUIRED:-0}" = "0" ]; then
        warn "当前 profile 未要求自动检查底盘网络"
        return 0
    fi
    if [ -z "${CAR_IP:-}" ]; then
        warn "当前 profile 未配置 CAR_IP，跳过底盘网络检查"
        return 0
    fi

    log "检查底盘网络 ($CAR_IP)..."
    if ping -c 1 -W 3 "$CAR_IP" > /dev/null 2>&1; then
        ok "底盘网络正常"
    else
        err "无法 ping 通底盘，请检查交换机连接或当前 profile"
        read -p "按 Enter 退出..."
        exit 1
    fi
}
chassis_node_running_ssh() {
    local check_cmd="${CHASSIS_NODE_CHECK_CMD:-}"
    if [ -z "$check_cmd" ]; then
        if [ -n "${CHASSIS_NODE_CHECK_PATTERN:-}" ]; then
            check_cmd="ros2 node list 2>/dev/null | grep -q ${CHASSIS_NODE_CHECK_PATTERN}"
        else
            return 1
        fi
    fi
    sshpass -p "$CAR_PASS" ssh -o StrictHostKeyChecking=no "$CAR_USER@$CAR_IP" "$check_cmd" 2>/dev/null
}
start_chassis() {
    case "${CHASSIS_START_MODE:-skip}" in
        skip)
            warn "当前 profile 未配置自动底盘启动，跳过底盘启动"
            ;;
        ssh_ros2)
            need_cmd sshpass
            if [ -z "${CAR_IP:-}" ] || [ -z "${CAR_USER:-}" ]; then
                err "ssh_ros2 底盘模式需要 CAR_IP 和 CAR_USER"
                exit 1
            fi
            if [ -z "${CAR_PASS:-}" ]; then
                err "ssh_ros2 底盘模式需要 CAR_PASS；请写入 config/profiles/${ROBOT_PROFILE}.local.env"
                exit 1
            fi
            log "检查底盘节点..."
            if chassis_node_running_ssh; then
                ok "底盘节点已运行"
            else
                [ -n "${CAR_LAUNCH_CMD:-}" ] || { err "未配置 CAR_LAUNCH_CMD"; exit 1; }
                log "远程启动底盘节点..."
                sshpass -p "$CAR_PASS" ssh -o StrictHostKeyChecking=no "$CAR_USER@$CAR_IP" \
                    "nohup bash -lc '${CAR_LAUNCH_CMD}' > ${CHASSIS_LOG_FILE} 2>&1 &" 2>/dev/null
                sleep 5
                ok "底盘启动命令已发送"
            fi
            ;;
        local_command)
            [ -n "${LOCAL_CHASSIS_LAUNCH_CMD:-}" ] || { err "local_command 底盘模式需要 LOCAL_CHASSIS_LAUNCH_CMD"; exit 1; }
            log "启动本地底盘驱动..."
            nohup setsid bash -lc "$LOCAL_CHASSIS_LAUNCH_CMD" > "$LOGDIR/chassis.log" 2>&1 &
            sleep 2
            ok "本地底盘启动命令已发送"
            ;;
        *)
            err "未知 CHASSIS_START_MODE: ${CHASSIS_START_MODE}"
            exit 1
            ;;
    esac
}
start_camera_driver() {
    case "${CAMERA_START_MODE:-skip}" in
        skip)
            warn "当前 profile 未配置自动相机启动，跳过相机驱动"
            ;;
        ros2_launch)
            [ -n "${CAMERA_LAUNCH_PACKAGE:-}" ] || { err "ros2_launch 相机模式需要 CAMERA_LAUNCH_PACKAGE"; exit 1; }
            [ -n "${CAMERA_LAUNCH_FILE:-}" ] || { err "ros2_launch 相机模式需要 CAMERA_LAUNCH_FILE"; exit 1; }
            reset_camera_usb
            log "启动 ${CAMERA_DRIVER_LABEL}..."
            nohup setsid ros2 launch "$CAMERA_LAUNCH_PACKAGE" "$CAMERA_LAUNCH_FILE" \
                "${CAMERA_LAUNCH_ARGS[@]}" \
                > "$LOGDIR/camera.log" 2>&1 &
            CAMERA_LAUNCH_PID=$!
            sleep 2
            if kill -0 "$CAMERA_LAUNCH_PID" 2>/dev/null; then
                ok "${CAMERA_DRIVER_LABEL} 启动进程已拉起，视频服务将先订阅并等待首帧"
            else
                warn "${CAMERA_DRIVER_LABEL} 启动进程已退出，检查 $LOGDIR/camera.log"
            fi
            ;;
        command)
            [ -n "${CAMERA_LAUNCH_CMD:-}" ] || { err "command 相机模式需要 CAMERA_LAUNCH_CMD"; exit 1; }
            reset_camera_usb
            log "启动 ${CAMERA_DRIVER_LABEL}..."
            nohup setsid bash -lc "$CAMERA_LAUNCH_CMD" > "$LOGDIR/camera.log" 2>&1 &
            sleep 2
            ok "${CAMERA_DRIVER_LABEL} 启动命令已发送"
            ;;
        *)
            err "未知 CAMERA_START_MODE: ${CAMERA_START_MODE}"
            exit 1
            ;;
    esac
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
start_control_gui() {
    [ "${START_CONTROL_GUI:-1}" = "1" ] || return 0
    if [ "$GUI_STARTED" = "1" ]; then
        return 0
    fi
    if pgrep -f "$SRC_DIR/car_gui.py" >/dev/null 2>&1; then
        GUI_STARTED=1
        ok "控制 GUI 已运行"
        return 0
    fi

    log "启动控制 GUI..."
    nohup env \
        CAR_GUI_CAMERA_SOURCE="${CAR_GUI_CAMERA_SOURCE:-auto}" \
        MJPEG_STREAM_URL="${MJPEG_STREAM_URL:-http://127.0.0.1:${MJPEG_PORT}/stream}" \
        python3 "$SRC_DIR/car_gui.py" \
        > "$LOGDIR/car_gui.log" 2>&1 &
    GUI_STARTED=1
}
trap stop_live_logs EXIT
trap 'stop_live_logs; exit 130' INT
trap 'stop_live_logs; exit 143' TERM

source_setup_files

UE_IP="$(pick_ue_ip)"
need_cmd ffmpeg
need_cmd mediamtx

echo "========================================"
echo "       小车全栈启动"
echo "========================================"
echo "  Profile: ${ROBOT_PROFILE} (${ROBOT_NAME})"
echo "  Chassis: ${CHASSIS_ADAPTER} / ${CHASSIS_START_MODE}"
echo "  Camera:  ${CAMERA_ADAPTER} / ${CAMERA_START_MODE}"

# ── 1. 杀掉旧进程 ────────────────────────────────────────────
log "清理旧进程..."
if [ "$REUSE_CAMERA" = "1" ] && camera_process_alive; then
    log "检测到已有相机进程，快速检查是否可复用..."
    if mjpeg_frame_ready 1 || camera_frame_ready "$CAMERA_REUSE_PROBE_TIMEOUT"; then
        CAMERA_REUSE_READY=1
        ok "已有相机正在出图，本次启动将复用相机进程"
    else
        warn "已有相机进程未在 ${CAMERA_REUSE_PROBE_TIMEOUT}s 内出图，将重启相机"
    fi
fi
pkill -f nmea_serial_driver   2>/dev/null || true
pkill -f rosbridge_bson_tcp.py 2>/dev/null || true
pkill -f rosbridge_tcp        2>/dev/null || true
pkill -f rosbridge_websocket  2>/dev/null || true
pkill -f u2r_r2u_bridge.py    2>/dev/null || true
if [ "$CAMERA_REUSE_READY" = "1" ]; then
    log "保留已运行的 ${CAMERA_DRIVER_LABEL}，跳过相机重启"
else
    stop_camera_processes
fi
pkill -f mjpeg_server         2>/dev/null || true
pkill -f rtsp_server          2>/dev/null || true
pkill -f mediamtx             2>/dev/null || true
pkill -f "rtsp://127.0.0.1:${RTSP_PORT}/robot_cam" 2>/dev/null || true
pkill -f car_gui              2>/dev/null || true
pkill -f ue_bridge            2>/dev/null || true
pkill -f keyboard_control.py  2>/dev/null || true
srun fuser -k "${ROSBRIDGE_PORT}/tcp"
srun fuser -k "${MJPEG_PORT}/tcp"
srun fuser -k "${RTSP_PORT}/tcp"
srun fuser -k "${RTSP_PORT}/udp"
srun fuser -k "${HLS_PORT}/tcp"
sleep 1

# ── 2. 检查小车连接 ──────────────────────────────────────────
check_chassis_network

# ── 3. 启动小车底盘节点（远程）───────────────────────────────
start_chassis

# ── 4. 验证 ROS2 话题 ────────────────────────────────────────
log "验证 ROS2 DDS..."
if [ "$REFRESH_ROS_DAEMON" = "1" ]; then
    ros2 daemon stop > /dev/null 2>&1
    sleep 1
fi
ros2 daemon start > /dev/null 2>&1 || true
sleep 0.5
if timeout 3s ros2 topic list 2>/dev/null | grep -q "${CMD_VEL_TOPIC}"; then
    ok "${CMD_VEL_TOPIC} 在线"
else
    warn "${CMD_VEL_TOPIC} 未发现，底盘可能未就绪（继续启动其他服务）"
fi

# ── 5. 启动相机节点 ──────────────────────────────────────────
if [ "$CAMERA_REUSE_READY" = "1" ]; then
    ok "复用已运行相机，跳过 ${CAMERA_DRIVER_LABEL} 初始化"
else
    start_camera_driver
fi

# ── 6. 提前启动视频服务，让订阅端在相机出首帧前就挂好 ─────────────
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

if [ "$START_GUI_EARLY" = "1" ]; then
    start_control_gui
fi

CAMERA_FIRST_FRAME_TIMEOUT="${CAMERA_FIRST_FRAME_TIMEOUT:-8}"
if [ "$CAMERA_FIRST_FRAME_TIMEOUT" != "0" ]; then
    log "快速检查相机首帧（最多 ${CAMERA_FIRST_FRAME_TIMEOUT}s，超时继续启动）..."
    if camera_frame_ready "$CAMERA_FIRST_FRAME_TIMEOUT"; then
        ok "相机首帧已收到"
    else
        warn "暂未收到相机首帧，继续启动；后续画面会在相机发布后自动出现"
    fi
fi

# ── 7. 启动 RTK（串口自动识别）──────────────────────────────
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

# ── 8. 启动 RTK / UE 数据流 ────────────────────────────────
log "启动 rosbridge TCP/BSON 兼容数据通道 (${ROSBRIDGE_PORT})..."
if python3 -c "import rosbridge_library, rosbridge_server" >/dev/null 2>&1; then
    start_live_log "rosbridge" "$ROSBRIDGE_LOG"
    nohup python3 "$SRC_DIR/rosbridge_bson_tcp.py" \
        --port "${ROSBRIDGE_PORT}" \
        --address 0.0.0.0 \
        > "$ROSBRIDGE_LOG" 2>&1 &
    sleep 3

    if ss -tln 2>/dev/null | grep -q ":${ROSBRIDGE_PORT}"; then
        ok "rosbridge TCP/BSON 已监听 ${ROSBRIDGE_PORT}"
    else
        warn "rosbridge TCP/BSON 未监听，检查 $ROSBRIDGE_LOG"
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

# ── 9. 启动 UE 指令桥接 ────────────────────────────────────
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

# ── 10. 启动控制 GUI ─────────────────────────────────────────
start_control_gui

echo ""
echo "========================================"
echo "  全栈启动完成"
echo "  Profile:  ${ROBOT_PROFILE} (${ROBOT_NAME})"
echo "  GPS/UE5:  ${UE_IP:-127.0.0.1}:${ROSBRIDGE_PORT}"
echo "  视频流:   rtsp://${UE_IP:-127.0.0.1}:${RTSP_PORT}/robot_cam"
echo "  UE(HLS):  http://${UE_IP:-127.0.0.1}:${HLS_PORT}${HLS_URL_PATH}"
echo "  HLS页:    http://${UE_IP:-127.0.0.1}:${HLS_PORT}${HLS_PREVIEW_PATH}"
echo "  浏览器:   http://${UE_IP:-127.0.0.1}:${MJPEG_PORT}/"
echo "  RTK位置:  ${RTK_POS_TOPIC} (${UE_PUBLISH_RATE:-1.0}Hz)"
echo "  UE指令:   tcp://${UE_IP:-127.0.0.1}:${ROSBRIDGE_PORT}  →  ${UE_COMMAND_TOPIC}"
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
