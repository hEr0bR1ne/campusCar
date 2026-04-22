#!/usr/bin/env python3
"""
UE Bridge - 接收 UE 通过 rosbridge 发来的 JSON 指令，控制小车运动
支持：
  1. 方向控制：Forward / TurnLeft / TurnRight / TurnBackward
  2. 坐标导航：直线行驶到目标经纬度

运行：source /opt/ros/humble/setup.bash && python3 ue_bridge.py
"""
import math
import threading
import time
import json

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, QuaternionStamped
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import String

# ── 配置 ──────────────────────────────────────────────────────────────────────
MAX_LINEAR_SPEED  = 1.0   # m/s
MAX_ANGULAR_SPEED = 1.0   # rad/s

CMD_TOPIC     = "/U2RTopic_Command"   # rosbridge 收到 UE 指令的话题
REPLY_TOPIC   = "/R2UTopic_Text"      # 回复 UE 的话题
FIX_TOPIC     = "/fix"
HEADING_TOPIC = "/heading"
CMD_VEL_TOPIC = "/cmd_vel"

# 导航参数
ARRIVE_THRESHOLD_M  = 0.5   # 距目标小于此距离视为到达（米）
HEADING_KP          = 1.2   # 转向比例系数
NAV_LINEAR_SPEED    = 0.3   # 导航时直行速度（m/s），独立于 speed 百分比
HEADING_TOLERANCE   = 0.15  # 朝向误差容忍（rad，约 8.6°）


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def quaternion_to_yaw(q) -> float:
    """四元数转 yaw（弧度，ENU 坐标系，北=π/2）"""
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


def haversine(lat1, lon1, lat2, lon2) -> float:
    """返回两点间距离（米）"""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing(lat1, lon1, lat2, lon2) -> float:
    """从点1到点2的方位角（弧度，ENU：东=0，北=π/2）"""
    dlam = math.radians(lon2 - lon1)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    # atan2 给的是从东方向逆时针，转成 ENU yaw
    return math.atan2(x, y)


def angle_diff(a, b) -> float:
    """a - b，结果归一化到 [-π, π]"""
    d = a - b
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


def speed_pct_to_ms(pct_str: str) -> float:
    """'30' -> 0.3 m/s"""
    try:
        pct = float(pct_str)
    except (ValueError, TypeError):
        pct = 30.0
    pct = max(0.0, min(100.0, pct))
    return MAX_LINEAR_SPEED * pct / 100.0


# ── ROS2 节点 ─────────────────────────────────────────────────────────────────

class UEBridgeNode(Node):
    def __init__(self):
        super().__init__("ue_bridge_node")

        self.pub_cmd   = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)
        self.pub_reply = self.create_publisher(String, REPLY_TOPIC, 10)

        self.create_subscription(String,             CMD_TOPIC,     self._on_command, 10)
        self.create_subscription(NavSatFix,          FIX_TOPIC,     self._on_fix,     10)
        self.create_subscription(QuaternionStamped,  HEADING_TOPIC, self._on_heading, 10)

        self._lock    = threading.Lock()
        self.lat      = None
        self.lon      = None
        self.yaw      = None   # 当前朝向（rad，ENU）

        # 导航任务状态
        self._nav_thread: threading.Thread | None = None
        self._nav_stop   = threading.Event()

        self.get_logger().info("UE Bridge 已启动，监听 " + CMD_TOPIC)

    # ── 传感器回调 ────────────────────────────────────────────────────────────

    def _on_fix(self, msg: NavSatFix):
        with self._lock:
            self.lat = msg.latitude
            self.lon = msg.longitude

    def _on_heading(self, msg: QuaternionStamped):
        with self._lock:
            self.yaw = quaternion_to_yaw(msg.quaternion)

    # ── 指令回调 ──────────────────────────────────────────────────────────────

    def _on_command(self, msg: String):
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warn("收到非法 JSON：" + msg.data)
            return

        if data.get("commandType") != "move":
            return

        params      = data.get("commandParams", {})
        destination = params.get("destination")
        speed_str   = params.get("speed", "30")
        cmd_id      = data.get("commandId", "")
        robot_id    = data.get("RobotId", "")

        if isinstance(destination, str):
            self._handle_direction(destination, speed_str)
        elif isinstance(destination, dict):
            self._handle_navigate(destination, speed_str, cmd_id, robot_id)
        else:
            self.get_logger().warn("未知 destination 格式")

    # ── 方向控制 ──────────────────────────────────────────────────────────────

    def _handle_direction(self, direction: str, speed_str: str):
        linear_spd  = speed_pct_to_ms(speed_str)
        angular_spd = MAX_ANGULAR_SPEED * float(speed_str) / 100.0

        twist = Twist()
        d = direction.strip().lower()
        if d == "forward":
            twist.linear.x  =  linear_spd
        elif d == "turnbackward":
            twist.linear.x  = -linear_spd
        elif d == "turnleft":
            twist.angular.z =  angular_spd
        elif d == "turnright":
            twist.angular.z = -angular_spd
        else:
            self.get_logger().warn("未知方向指令：" + direction)
            return

        self._cancel_nav()
        self.pub_cmd.publish(twist)
        self.get_logger().info(f"方向指令：{direction}  速度：{linear_spd:.2f} m/s")

    # ── 坐标导航 ──────────────────────────────────────────────────────────────

    def _handle_navigate(self, dest: dict, speed_str: str, cmd_id: str, robot_id: str):
        target_lon = float(dest.get("x", 0))
        target_lat = float(dest.get("y", 0))
        linear_spd = speed_pct_to_ms(speed_str)

        with self._lock:
            if self.lat is None or self.lon is None:
                self.get_logger().error("GPS 未就绪，无法导航")
                return
            if self.yaw is None:
                self.get_logger().error("朝向未就绪，无法导航")
                return

        self.get_logger().info(
            f"导航目标：lat={target_lat}, lon={target_lon}  速度：{linear_spd:.2f} m/s"
        )
        self._cancel_nav()
        self._nav_stop.clear()
        self._nav_thread = threading.Thread(
            target=self._nav_loop,
            args=(target_lat, target_lon, linear_spd, cmd_id, robot_id),
            daemon=True,
        )
        self._nav_thread.start()

    def _nav_loop(self, target_lat, target_lon, linear_spd, cmd_id, robot_id):
        """导航主循环：先对准方向，再直行，到达后停止"""
        rate_hz = 10
        dt = 1.0 / rate_hz

        while not self._nav_stop.is_set():
            with self._lock:
                cur_lat = self.lat
                cur_lon = self.lon
                cur_yaw = self.yaw

            if cur_lat is None or cur_yaw is None:
                time.sleep(dt)
                continue

            dist = haversine(cur_lat, cur_lon, target_lat, target_lon)
            if dist < ARRIVE_THRESHOLD_M:
                self._publish_twist(0.0, 0.0)
                self.get_logger().info("已到达目标点")
                self._reply(cmd_id, robot_id, "arrived")
                return

            target_bearing = bearing(cur_lat, cur_lon, target_lat, target_lon)
            err = angle_diff(target_bearing, cur_yaw)

            if abs(err) > HEADING_TOLERANCE:
                # 先原地转向对准目标
                angular = max(-MAX_ANGULAR_SPEED,
                              min(MAX_ANGULAR_SPEED, HEADING_KP * err))
                self._publish_twist(0.0, angular)
            else:
                # 朝向对准，直行
                self._publish_twist(linear_spd, 0.0)

            time.sleep(dt)

        # 被取消时停车
        self._publish_twist(0.0, 0.0)

    def _cancel_nav(self):
        if self._nav_thread and self._nav_thread.is_alive():
            self._nav_stop.set()
            self._nav_thread.join(timeout=1.0)

    # ── 工具 ──────────────────────────────────────────────────────────────────

    def _publish_twist(self, linear: float, angular: float):
        t = Twist()
        t.linear.x  = linear
        t.angular.z = angular
        self.pub_cmd.publish(t)

    def _reply(self, cmd_id: str, robot_id: str, status: str):
        payload = json.dumps({
            "commandId": cmd_id,
            "RobotId":   robot_id,
            "status":    status,
        })
        msg = String()
        msg.data = payload
        self.pub_reply.publish(msg)


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    rclpy.init()
    node = UEBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._cancel_nav()
        node._publish_twist(0.0, 0.0)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
