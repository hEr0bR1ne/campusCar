#!/usr/bin/env python3
"""
路径记录节点 - 记录 GPS 轨迹并在 RViz 中可视化
用法:
  python3 path_recorder.py              # 交互式键盘控制
  python3 path_recorder.py --auto       # 自动开始记录（启动即录）

快捷键:
  r  - 开始/停止记录
  s  - 保存路径到文件
  c  - 清除当前路径
  q  - 退出
"""
import sys
import os
import json
import math
import time
import threading
import argparse
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from sensor_msgs.msg import NavSatFix
from nav_msgs.msg import Path
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import Header, ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray
from builtin_interfaces.msg import Duration

from config import TOPIC_FIX_IN, ROOT_DIR
from core.gnss import GNSSValidator

# 路径保存目录
PATH_SAVE_DIR = ROOT_DIR / "data" / "recorded_paths"


def gps_to_enu(lat, lon, alt, lat0, lon0, alt0):
    """将 GPS 经纬度转换为以 (lat0, lon0, alt0) 为原点的 ENU 局部坐标（米）"""
    R = 6378137.0  # WGS84 地球半径
    d_lat = math.radians(lat - lat0)
    d_lon = math.radians(lon - lon0)
    lat_r = math.radians(lat0)

    east  = R * d_lon * math.cos(lat_r)
    north = R * d_lat
    up    = alt - alt0
    return east, north, up


class PathRecorderNode(Node):
    def __init__(self, auto_start=False):
        super().__init__("path_recorder")

        # 状态
        self.recording = False
        self.waypoints = []          # list of (lat, lon, alt, timestamp)
        self.origin = None           # (lat0, lon0, alt0) 第一个点作为原点
        self.last_lat = None
        self.last_lon = None
        self.min_dist_m = 0.3        # 最小采样间距（米），避免重复点

        # QoS: latched topic 让 RViz 重连后也能看到历史路径
        latched_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )

        # 发布 nav_msgs/Path（RViz 标准路径消息）
        self.pub_path = self.create_publisher(Path, "/recorded_path", latched_qos)
        # 发布 MarkerArray（带编号的路径点标记）
        self.pub_markers = self.create_publisher(MarkerArray, "/recorded_path_markers", latched_qos)

        # 订阅 GPS
        self.sub_fix = self.create_subscription(
            NavSatFix, TOPIC_FIX_IN, self._on_fix, 10
        )

        # 定时刷新发布（1Hz，保持 RViz 显示）
        self.create_timer(1.0, self._publish_path)

        if auto_start:
            self.recording = True
            self.get_logger().info("自动开始记录路径...")

        self.get_logger().info("路径记录节点已启动")
        self.get_logger().info(f"  路径话题: /recorded_path  (nav_msgs/Path)")
        self.get_logger().info(f"  标记话题: /recorded_path_markers  (visualization_msgs/MarkerArray)")

    def _on_fix(self, msg: NavSatFix):
        if not self.recording:
            return
        if msg.status.status < 0:
            return  # 无信号
        if not GNSSValidator.is_valid(msg.latitude, msg.longitude):
            return

        lat, lon, alt = msg.latitude, msg.longitude, msg.altitude

        # 设置原点
        if self.origin is None:
            self.origin = (lat, lon, alt)
            self.get_logger().info(f"原点设置: lat={lat:.6f}, lon={lon:.6f}")

        # 距离过滤
        if self.last_lat is not None:
            e, n, _ = gps_to_enu(lat, lon, alt, self.last_lat, self.last_lon, alt)
            dist = math.sqrt(e*e + n*n)
            if dist < self.min_dist_m:
                return

        self.last_lat = lat
        self.last_lon = lon
        self.waypoints.append((lat, lon, alt, time.time()))
        self._publish_path()

        count = len(self.waypoints)
        if count % 10 == 0 or count <= 5:
            e, n, u = gps_to_enu(lat, lon, alt, *self.origin)
            print(f"\r[记录] #{count:4d}  Lat:{lat:.6f} Lon:{lon:.6f}  ENU:({e:+.1f},{n:+.1f})m    ",
                  end="", flush=True)

    def _publish_path(self):
        if not self.waypoints or self.origin is None:
            return

        now = self.get_clock().now().to_msg()
        lat0, lon0, alt0 = self.origin

        # --- nav_msgs/Path ---
        path_msg = Path()
        path_msg.header.stamp = now
        path_msg.header.frame_id = "map"

        for lat, lon, alt, _ in self.waypoints:
            e, n, u = gps_to_enu(lat, lon, alt, lat0, lon0, alt0)
            ps = PoseStamped()
            ps.header.stamp = now
            ps.header.frame_id = "map"
            ps.pose.position.x = e
            ps.pose.position.y = n
            ps.pose.position.z = u
            ps.pose.orientation.w = 1.0
            path_msg.poses.append(ps)

        self.pub_path.publish(path_msg)

        # --- MarkerArray: 路径线 + 起终点标记 ---
        markers = MarkerArray()

        # 路径线条
        line = Marker()
        line.header.stamp = now
        line.header.frame_id = "map"
        line.ns = "path_line"
        line.id = 0
        line.type = Marker.LINE_STRIP
        line.action = Marker.ADD
        line.scale.x = 0.1  # 线宽 0.1m
        line.color.r = 0.0
        line.color.g = 0.8
        line.color.b = 1.0
        line.color.a = 1.0
        line.lifetime = Duration(sec=0, nanosec=0)  # 永久显示

        for lat, lon, alt, _ in self.waypoints:
            from geometry_msgs.msg import Point
            e, n, u = gps_to_enu(lat, lon, alt, lat0, lon0, alt0)
            p = Point()
            p.x = e; p.y = n; p.z = u
            line.points.append(p)
        markers.markers.append(line)

        # 起点（绿色球）
        start = Marker()
        start.header.stamp = now
        start.header.frame_id = "map"
        start.ns = "path_endpoints"
        start.id = 1
        start.type = Marker.SPHERE
        start.action = Marker.ADD
        start.scale.x = start.scale.y = start.scale.z = 0.5
        start.color.r = 0.0; start.color.g = 1.0; start.color.b = 0.0; start.color.a = 1.0
        e, n, u = gps_to_enu(*self.waypoints[0][:3], lat0, lon0, alt0)
        start.pose.position.x = e
        start.pose.position.y = n
        start.pose.position.z = u + 0.3
        start.pose.orientation.w = 1.0
        markers.markers.append(start)

        # 当前末端（红色球）
        end = Marker()
        end.header.stamp = now
        end.header.frame_id = "map"
        end.ns = "path_endpoints"
        end.id = 2
        end.type = Marker.SPHERE
        end.action = Marker.ADD
        end.scale.x = end.scale.y = end.scale.z = 0.5
        end.color.r = 1.0; end.color.g = 0.2; end.color.b = 0.0; end.color.a = 1.0
        e, n, u = gps_to_enu(*self.waypoints[-1][:3], lat0, lon0, alt0)
        end.pose.position.x = e
        end.pose.position.y = n
        end.pose.position.z = u + 0.3
        end.pose.orientation.w = 1.0
        markers.markers.append(end)

        self.pub_markers.publish(markers)

    def start_recording(self):
        self.recording = True
        print(f"\n[路径记录] ▶ 开始记录  (已有 {len(self.waypoints)} 个点)")

    def stop_recording(self):
        self.recording = False
        print(f"\n[路径记录] ■ 停止记录  (共 {len(self.waypoints)} 个点)")

    def clear_path(self):
        self.waypoints.clear()
        self.origin = None
        self.last_lat = None
        self.last_lon = None
        # 发布空路径清除 RViz 显示
        now = self.get_clock().now().to_msg()
        empty = Path()
        empty.header.stamp = now
        empty.header.frame_id = "map"
        self.pub_path.publish(empty)
        # 清除 markers
        clear_markers = MarkerArray()
        for mid in [0, 1, 2]:
            m = Marker()
            m.header.stamp = now
            m.header.frame_id = "map"
            m.ns = "path_line" if mid == 0 else "path_endpoints"
            m.id = mid
            m.action = Marker.DELETE
            clear_markers.markers.append(m)
        self.pub_markers.publish(clear_markers)
        print("\n[路径记录] 路径已清除")

    def save_path(self, filename=None):
        if not self.waypoints:
            print("\n[路径记录] 没有可保存的路径点")
            return None

        PATH_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        if filename is None:
            filename = f"path_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = PATH_SAVE_DIR / filename

        lat0, lon0, alt0 = self.origin
        data = {
            "recorded_at": datetime.now().isoformat(),
            "point_count": len(self.waypoints),
            "origin": {"lat": lat0, "lon": lon0, "alt": alt0},
            "waypoints": [
                {
                    "index": i,
                    "lat": lat,
                    "lon": lon,
                    "alt": alt,
                    "timestamp": ts,
                    "enu": {
                        "east":  round(gps_to_enu(lat, lon, alt, lat0, lon0, alt0)[0], 4),
                        "north": round(gps_to_enu(lat, lon, alt, lat0, lon0, alt0)[1], 4),
                        "up":    round(gps_to_enu(lat, lon, alt, lat0, lon0, alt0)[2], 4),
                    }
                }
                for i, (lat, lon, alt, ts) in enumerate(self.waypoints)
            ]
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"\n[路径记录] 已保存 {len(self.waypoints)} 个点 -> {filepath}")
        return str(filepath)


def keyboard_loop(node: PathRecorderNode):
    """在独立线程中处理键盘输入"""
    import tty
    import termios

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    print("\n" + "=" * 55)
    print("  路径记录控制台")
    print("=" * 55)
    print("  r  - 开始 / 停止记录")
    print("  s  - 保存路径到文件")
    print("  c  - 清除当前路径")
    print("  q  - 退出")
    print("=" * 55)
    print(f"  GPS 话题: {TOPIC_FIX_IN}")
    print(f"  RViz 路径话题: /recorded_path")
    print(f"  保存目录: {PATH_SAVE_DIR}")
    print("=" * 55 + "\n")

    try:
        tty.setraw(fd)
        while rclpy.ok():
            ch = sys.stdin.read(1)
            if ch == 'r':
                if node.recording:
                    node.stop_recording()
                else:
                    node.start_recording()
            elif ch == 's':
                node.save_path()
            elif ch == 'c':
                node.clear_path()
            elif ch in ('q', '\x03'):  # q 或 Ctrl+C
                print("\n[路径记录] 退出...")
                rclpy.shutdown()
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    parser = argparse.ArgumentParser(description="GPS 路径记录节点")
    parser.add_argument("--auto", action="store_true", help="启动即自动开始记录")
    parser.add_argument("--min-dist", type=float, default=0.3,
                        help="最小采样间距（米），默认 0.3m")
    args = parser.parse_args()

    rclpy.init()
    node = PathRecorderNode(auto_start=args.auto)
    node.min_dist_m = args.min_dist

    # 键盘线程
    kb_thread = threading.Thread(target=keyboard_loop, args=(node,), daemon=True)
    kb_thread.start()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # 退出前自动保存（如果有未保存的点）
        if node.waypoints:
            print("\n[路径记录] 自动保存退出前路径...")
            node.save_path()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
