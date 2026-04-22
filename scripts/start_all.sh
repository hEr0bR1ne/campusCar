#!/bin/bash
# ============================================================
# rosCar 全栈一键启动脚本
# 包含：底盘节点（小车端）验证 + RTK 全栈（NUC 端）
# ============================================================

set -e

CAR_IP="192.168.100.2"
CAR_USER="bingda"
CAR_PASS="bingda"
RTK_DIR="$HOME/RTK_project"

echo "========================================"
echo "  rosCar + RTK 全栈启动"
echo "========================================"

# ------- Step 1: 检查小车连接 -------
echo ""
echo "[1/3] 检查小车网络连通性 ($CAR_IP)..."
if ! ping -c 1 -W 3 "$CAR_IP" > /dev/null 2>&1; then
    echo "❌ 无法 ping 通小车 ($CAR_IP)，请检查交换机连接"
    exit 1
fi
echo "✅ 小车网络正常 (ping OK)"

# ------- Step 2: 检查底盘节点是否已在小车上运行 -------
echo ""
echo "[2/3] 检查小车底盘节点..."

# 用 sshpass 非交互检查
if sshpass -p "$CAR_PASS" ssh -o StrictHostKeyChecking=no "$CAR_USER@$CAR_IP" \
    "ros2 node list 2>/dev/null | grep -q base_control" 2>/dev/null; then
    echo "✅ 底盘节点已运行"
else
    echo "⚠️  底盘节点未运行，正在远程启动..."
    echo "   (会在小车后台启动，日志写入 ~/ros2_base_control.log)"
    sshpass -p "$CAR_PASS" ssh -o StrictHostKeyChecking=no "$CAR_USER@$CAR_IP" \
        "nohup bash -lc 'source ~/ros2_ws/install/setup.bash && ros2 launch base_control_ros2 base_control.launch.py' \
         > ~/ros2_base_control.log 2>&1 &" 2>/dev/null
    echo "   等待底盘节点初始化 (5秒)..."
    sleep 5
    echo "✅ 底盘启动命令已发送"
fi

# ------- Step 3: 验证 ROS2 话题发现 -------
echo ""
echo "[3/3] 验证 ROS2 DDS 话题发现..."
sleep 1
TOPICS=$(ros2 topic list 2>/dev/null)
if echo "$TOPICS" | grep -q "/cmd_vel"; then
    echo "✅ /cmd_vel 在线 (底盘就绪)"
else
    echo "⚠️  /cmd_vel 未发现，重启 ROS2 daemon..."
    ros2 daemon stop && sleep 1 && ros2 daemon start
    sleep 3
    TOPICS=$(ros2 topic list 2>/dev/null)
    if echo "$TOPICS" | grep -q "/cmd_vel"; then
        echo "✅ /cmd_vel 在线 (底盘就绪)"
    else
        echo "❌ 底盘话题仍未出现，请手动检查小车端"
        echo "   手动命令: ssh $CAR_USER@$CAR_IP"
        echo "             source ~/ros2_ws/install/setup.bash"
        echo "             ros2 launch base_control_ros2 base_control.launch.py"
    fi
fi

# ------- Step 4: 启动 RTK 全栈 -------
echo ""
echo "[4/4] 启动 RTK 全栈..."
if ! [ -f "$RTK_DIR/rtk_tools/app.py" ]; then
    echo "❌ RTK 工程未找到：$RTK_DIR/rtk_tools/app.py"
    exit 1
fi

cd "$RTK_DIR"
python3 rtk_tools/app.py start

echo ""
echo "========================================"
echo "  全栈启动完成"
echo "  底盘控制:  ros2 run teleop_twist_keyboard teleop_twist_keyboard"
echo "           或: python3 ~/rosCar/move.py"
echo "  UE5 连接: $(hostname -I | awk '{print $1}'):9090"
echo "========================================"
