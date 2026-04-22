#!/bin/bash
# ============================================================
# campusCar 全栈停止脚本
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_ROOT}/config/robot.env"
SRC_DIR="${PROJECT_ROOT}/src"

echo "========================================"
echo "  campusCar 全栈停止"
echo "========================================"

echo ""
echo "[1/3] 停止 RTK 全栈..."
pkill -f "nmea_serial_driver"  2>/dev/null && echo "✅ nmea_serial_driver 已停止" || true
pkill -f "rosbridge"           2>/dev/null && echo "✅ rosbridge 已停止" || true
pkill -f "u2r_r2u_bridge.py"  2>/dev/null && echo "✅ u2r_r2u_bridge 已停止" || true

echo ""
echo "[2/3] 停止视频与相机相关进程..."
pkill -f "rtsp_server.py"      2>/dev/null && echo "✅ rtsp_server 已停止" || true
pkill -f "mjpeg_server.py"     2>/dev/null && echo "✅ mjpeg_server 已停止" || true
pkill -f "mediamtx"            2>/dev/null && echo "✅ mediamtx 已停止" || true
pkill -f "ffmpeg"              2>/dev/null && echo "✅ ffmpeg 已停止" || true
pkill -f "image_flipper.py"    2>/dev/null && echo "✅ image_flipper 已停止" || true
pkill -f "orbbec_camera"       2>/dev/null && echo "✅ 相机 launch 已停止" || true

echo ""
echo "[3/3] 停止控制相关进程..."
pkill -f "car_gui.py"          2>/dev/null && echo "✅ car_gui 已停止" || true
pkill -f "ue_bridge.py"        2>/dev/null && echo "✅ ue_bridge 已停止" || true
pkill -f "move.py"             2>/dev/null && echo "✅ move.py 已停止" || true

echo ""
echo "✅ 全栈已停止"
