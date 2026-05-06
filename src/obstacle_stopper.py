#!/usr/bin/env python3
"""
obstacle_stopper.py - 激光雷达避障仲裁节点

话题流：
  /cmd_vel_input  (来自现有控制节点，通过 CMD_VEL_TOPIC 重定向)
  /scan           (来自 Docker 容器内激光雷达驱动)
  ──> /cmd_vel    (输出给底盘 base_control_ros2)

避障逻辑（初期：刹停保护）：
  - 检测前方扇区内最近障碍距离 d
  - d > OBSTACLE_WARN_DIST：透传原始指令
  - OBSTACLE_STOP_DIST < d < OBSTACLE_WARN_DIST：线速度按比例减速，保留转向
  - d < OBSTACLE_STOP_DIST：刹停，仅允许后退和原地转向脱困

Fail-open 设计：
  - /scan 超时（激光雷达断开）时自动退化为透传模式
  - OBSTACLE_ENABLED=0 时完全透传

后期扩展：
  - 在 _tick() 中添加 'avoid' 状态实现 VFH 绕障
  - 不需要修改其他任何文件
"""
import math
import os
import time
import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSProfile,
    ReliabilityPolicy,
    DurabilityPolicy,
    HistoryPolicy,
    qos_profile_sensor_data,
)
from geometry_msgs.msg import Twist
from sensor_msgs.msg import LaserScan

# ---- 配置参数（从环境变量读取，与 robot.env 风格一致）----
OBSTACLE_STOP_DIST   = float(os.getenv("OBSTACLE_STOP_DIST",   "0.5"))   # m，刹停距离
OBSTACLE_WARN_DIST   = float(os.getenv("OBSTACLE_WARN_DIST",   "3.0"))   # m，开始减速距离
OBSTACLE_FRONT_DEG   = float(os.getenv("OBSTACLE_FRONT_ANGLE_DEG", "30")) # 前方检测扇区半角（度）
OBSTACLE_ENABLED     = os.getenv("OBSTACLE_ENABLED", "1") == "1"
SCAN_TIMEOUT_SEC     = float(os.getenv("OBSTACLE_SCAN_TIMEOUT", "2.0"))   # scan 超时退化为透传
CMD_VEL_INPUT_TOPIC  = os.getenv("CMD_VEL_INPUT_TOPIC",  "/cmd_vel_input")
CMD_VEL_OUTPUT_TOPIC = os.getenv("CMD_VEL_OUTPUT_TOPIC", "/cmd_vel")
SCAN_TOPIC           = os.getenv("SCAN_TOPIC", "/scan")
PUBLISH_RATE_HZ      = float(os.getenv("OBSTACLE_PUBLISH_RATE_HZ", "20.0"))
LOG_INTERVAL_TICKS   = int(os.getenv("OBSTACLE_LOG_INTERVAL", "40"))  # 每 N 个 tick 打印一次调参日志


class ObstacleStopper(Node):
    def __init__(self):
        super().__init__("obstacle_stopper")

        # 底盘 QoS：BEST_EFFORT，与 base_control_ros2 订阅匹配
        chassis_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
        )
        self._pub = self.create_publisher(Twist, CMD_VEL_OUTPUT_TOPIC, chassis_qos)

        # 订阅控制指令（来自现有控制节点）
        self._sub_cmd = self.create_subscription(
            Twist, CMD_VEL_INPUT_TOPIC, self._on_cmd_vel, 10
        )
        # 订阅激光雷达扫描（来自 Docker 容器）
        self._sub_scan = self.create_subscription(
            LaserScan, SCAN_TOPIC, self._on_scan, qos_profile_sensor_data
        )

        self._lock = threading.Lock()
        self._latest_cmd = Twist()          # 最新来自控制节点的指令
        self._cmd_received_at = 0.0
        self._min_front_dist = float("inf") # 前方最近障碍距离
        self._scan_received_at = 0.0
        self._obstacle_state = "init"       # init / clear / warn / stop / scan_timeout
        self._tick_count = 0

        self.create_timer(1.0 / PUBLISH_RATE_HZ, self._tick)

        self.get_logger().info(
            f"避障仲裁节点已启动\n"
            f"  输入: {CMD_VEL_INPUT_TOPIC} + {SCAN_TOPIC}\n"
            f"  输出: {CMD_VEL_OUTPUT_TOPIC}\n"
            f"  刹停距离={OBSTACLE_STOP_DIST}m  减速距离={OBSTACLE_WARN_DIST}m  "
            f"前方扇区=±{OBSTACLE_FRONT_DEG}°\n"
            f"  {'[避障已启用]' if OBSTACLE_ENABLED else '[避障已禁用，透传模式]'}"
        )

    def _on_cmd_vel(self, msg: Twist):
        with self._lock:
            self._latest_cmd = msg
            self._cmd_received_at = time.monotonic()

    def _on_scan(self, msg: LaserScan):
        """计算前方扇区内最近障碍距离"""
        front_rad = math.radians(OBSTACLE_FRONT_DEG)
        angle = msg.angle_min
        min_dist = float("inf")

        for r in msg.ranges:
            # 前方扇区：angle 在 [-front_rad, front_rad]
            if abs(angle) <= front_rad:
                if msg.range_min <= r <= msg.range_max and math.isfinite(r):
                    min_dist = min(min_dist, r)
            angle += msg.angle_increment

        with self._lock:
            self._min_front_dist = min_dist
            self._scan_received_at = time.monotonic()

    def _tick(self):
        now = time.monotonic()
        self._tick_count += 1

        with self._lock:
            cmd = self._latest_cmd
            scan_age = now - self._scan_received_at
            dist = self._min_front_dist

        # ---- 情况 1：scan 超时（激光雷达断开），退化为透传 ----
        if scan_age > SCAN_TIMEOUT_SEC:
            if self._obstacle_state != "scan_timeout":
                self.get_logger().warn(
                    f"[避障] /scan 超时 {scan_age:.1f}s，退化为透传模式（激光雷达断开？）"
                )
                self._obstacle_state = "scan_timeout"
            self._pub.publish(cmd)
            return

        # ---- 情况 2：避障已禁用，完全透传 ----
        if not OBSTACLE_ENABLED:
            self._pub.publish(cmd)
            return

        # ---- 情况 3：避障逻辑 ----
        if dist < OBSTACLE_STOP_DIST:
            # 刹停：只允许后退（linear.x < 0）和原地转向脱困
            out = Twist()
            if cmd.linear.x < 0:
                out.linear.x = cmd.linear.x  # 允许后退脱困
            out.angular.z = cmd.angular.z     # 允许原地转向

            if self._obstacle_state != "stop":
                self.get_logger().warn(
                    f"[避障] 前方 {dist:.2f}m 有障碍，刹停！"
                    f"（阈值={OBSTACLE_STOP_DIST}m）"
                )
                self._obstacle_state = "stop"
            self._pub.publish(out)

        elif dist < OBSTACLE_WARN_DIST:
            # 减速：线速度按距离比例缩减，保留转向
            scale = (dist - OBSTACLE_STOP_DIST) / (OBSTACLE_WARN_DIST - OBSTACLE_STOP_DIST)
            scale = max(0.0, min(1.0, scale))  # 限制在 [0, 1]
            out = Twist()
            out.linear.x  = cmd.linear.x * scale
            out.linear.y  = cmd.linear.y * scale
            out.angular.z = cmd.angular.z

            if self._obstacle_state != "warn":
                self.get_logger().info(
                    f"[避障] 前方 {dist:.2f}m 有障碍，减速至 {scale*100:.0f}%"
                )
                self._obstacle_state = "warn"
            self._pub.publish(out)

        else:
            # 无障碍：透传
            if self._obstacle_state not in ("clear", "init"):
                self.get_logger().info(
                    f"[避障] 障碍已清除（前方 {dist:.2f}m），恢复正常速度"
                )
            self._obstacle_state = "clear"
            self._pub.publish(cmd)

        # ---- 调参日志（每 LOG_INTERVAL_TICKS 个 tick 打印一次）----
        if self._tick_count % LOG_INTERVAL_TICKS == 0:
            self.get_logger().info(
                f"[避障状态] state={self._obstacle_state}  "
                f"前方最近={dist:.2f}m  "
                f"scan_age={scan_age:.2f}s  "
                f"cmd_in=(vx={cmd.linear.x:.2f} wz={cmd.angular.z:.2f})"
            )


def main():
    rclpy.init()
    node = ObstacleStopper()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
