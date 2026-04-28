#!/usr/bin/env python3
"""
小车控制 GUI
功能：键盘控制 / 摄像头图像 / 经纬度显示 / 路径录制
运行：source /opt/ros/humble/setup.bash && python3 car_gui.py
"""
import sys
import os
import shlex
import socket
import subprocess
import threading
import time
import json
import math
from urllib.error import URLError
from urllib.request import Request, urlopen
from pathlib import Path
from datetime import datetime

CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "robot.env"

# ── ROS2 ──────────────────────────────────────────────────────────────────────
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import NavSatFix, Image, CompressedImage, Imu
from std_msgs.msg import String
from motion_profile import shape_twist_for_base

# ── GUI ───────────────────────────────────────────────────────────────────────
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
import cv2
import numpy as np
from PIL import Image as PILImage, ImageTk

# ── 配置 ──────────────────────────────────────────────────────────────────────

def load_project_env():
    env_file = CONFIG_FILE
    if not env_file.exists():
        return

    original_env = set(os.environ)
    command = f"set -a; source {shlex.quote(str(env_file))}; env -0"
    try:
        result = subprocess.run(
            ["bash", "-lc", command],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.CalledProcessError):
        return

    for entry in result.stdout.split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        key_b, value_b = entry.split(b"=", 1)
        try:
            key = key_b.decode()
            value = value_b.decode()
        except UnicodeDecodeError:
            continue
        if key in original_env:
            continue
        if key.replace("_", "").isalnum() and not key[0].isdigit():
            os.environ[key] = value


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, ""))
    except ValueError:
        return default


def env_list(name: str) -> list[str]:
    value = os.getenv(name, "")
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


load_project_env()

CMD_VEL_TOPIC   = env_str("CMD_VEL_TOPIC", "/cmd_vel")
FIX_TOPIC       = env_str("FIX_TOPIC", "/fix")
IMU_TOPIC       = env_str("IMU_TOPIC", "/imu")
ODOM_TOPIC      = env_str("ODOM_TOPIC", "/odom")
IMAGE_TOPIC     = env_str("IMAGE_TOPIC", "/camera/color/image_raw")
IMAGE_TOPIC_CANDIDATES = list(dict.fromkeys([
    IMAGE_TOPIC,
    *env_list("IMAGE_TOPIC_ALIASES"),
]))
COMPRESSED_TOPIC_CANDIDATES = list(dict.fromkeys([
    f"{topic}/compressed" for topic in IMAGE_TOPIC_CANDIDATES
]))
UE_COMMAND_TOPIC = env_str("UE_COMMAND_TOPIC", "/U2RTopic_Command")
RTK_POS_TOPIC    = env_str("RTK_POS_TOPIC", "/R2UTopic_Pos")
RTK_TEXT_TOPIC   = env_str("RTK_TEXT_TOPIC", "/R2UTopic_Text")
ROSBRIDGE_PORT   = env_int("ROSBRIDGE_PORT", 9090)
MJPEG_PORT       = env_int("MJPEG_PORT", 8080)
CAMERA_GUI_SOURCE = env_str("CAR_GUI_CAMERA_SOURCE", env_str("CAMERA_GUI_SOURCE", "auto")).lower()
MJPEG_STREAM_URL = env_str("MJPEG_STREAM_URL", f"http://127.0.0.1:{MJPEG_PORT}/stream")
MJPEG_CONNECT_TIMEOUT_SEC = env_float("MJPEG_CONNECT_TIMEOUT_SEC", 1.5)
MJPEG_RECONNECT_SEC = env_float("MJPEG_RECONNECT_SEC", 0.5)
MJPEG_BUFFER_LIMIT = 2 * 1024 * 1024
CAMERA_WAIT_LABEL = "MJPEG/ROS 图像" if CAMERA_GUI_SOURCE in ("auto", "mjpeg", "http") else IMAGE_TOPIC
VEHICLE_HEADING_OFFSET_DEG = env_float("VEHICLE_HEADING_OFFSET_DEG", 0.0)
NORTH_YAW_ENU_DEG = 90.0

LINEAR_SPEED    = 0.3   # m/s
ANGULAR_SPEED   = 0.5   # rad/s
CMD_REPEAT_MS   = 50
KEY_RELEASE_DEBOUNCE_MS = 120
RECORD_DIR      = Path(__file__).parent.parent / "data" / "recorded_paths"

MOVE_KEYS = {"w", "a", "s", "d", "up", "down", "left", "right"}

SPEED_BINDINGS = {
    "q": (1.1, 1.1),
    "z": (0.9, 0.9),
    "r": (1.1, 1.0),
    "f": (0.9, 1.0),
    "t": (1.0, 1.1),
    "g": (1.0, 0.9),
}

TOPICS_TO_MONITOR = [
    (FIX_TOPIC, "RTK原始"),
    (IMU_TOPIC, "底盘IMU"),
    (ODOM_TOPIC, "里程计"),
    (IMAGE_TOPIC, "相机图像"),
    (RTK_POS_TOPIC, "UE坐标"),
    (UE_COMMAND_TOPIC, "UE指令"),
    (RTK_TEXT_TOPIC, "UE回复"),
    (CMD_VEL_TOPIC, "底盘控制"),
]

# ── 颜色主题 ──────────────────────────────────────────────────────────────────
BG       = "#1e1e2e"
BG2      = "#2a2a3e"
ACCENT   = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"
TEXT     = "#cdd6f4"
SUBTEXT  = "#6c7086"
PANEL    = "#232337"
PANEL2   = "#171724"

# 字体（在 main() 里 tk.Tk() 之后初始化，避免 rclpy 信号冲突）
FONT_TITLE = FONT_NORMAL = FONT_SMALL = FONT_CARD = FONT_BTN = FONT_MONO = None


def quaternion_to_yaw(q) -> float:
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


def normalize_degrees(value: float) -> float:
    return value % 360.0


def normalize_offset_degrees(value: float) -> float:
    return ((value + 180.0) % 360.0) - 180.0


def raw_yaw_deg_from_quaternion(q) -> float:
    return normalize_degrees(math.degrees(quaternion_to_yaw(q)))


def calibrated_yaw_deg(raw_yaw_deg: float) -> float:
    return normalize_degrees(raw_yaw_deg + VEHICLE_HEADING_OFFSET_DEG)


def yaw_deg_from_quaternion(q) -> float:
    return calibrated_yaw_deg(raw_yaw_deg_from_quaternion(q))


def set_vehicle_heading_offset(value: float):
    global VEHICLE_HEADING_OFFSET_DEG
    VEHICLE_HEADING_OFFSET_DEG = normalize_offset_degrees(value)
    os.environ["VEHICLE_HEADING_OFFSET_DEG"] = f"{VEHICLE_HEADING_OFFSET_DEG:.3f}"


def persist_vehicle_heading_offset(value: float):
    value = normalize_offset_degrees(value)
    new_line = f"VEHICLE_HEADING_OFFSET_DEG={value:.3f}"

    text = CONFIG_FILE.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    replaced = False
    for idx, line in enumerate(lines):
        if line.lstrip().startswith("VEHICLE_HEADING_OFFSET_DEG="):
            lines[idx] = new_line + ("\n" if line.endswith("\n") else "")
            replaced = True
            break

    if not replaced:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line + "\n")

    CONFIG_FILE.write_text("".join(lines), encoding="utf-8")


def finite_or_none(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


# ══════════════════════════════════════════════════════════════════════════════
# ROS2 节点（后台线程）
# ══════════════════════════════════════════════════════════════════════════════
class CarNode(Node):
    def __init__(self):
        super().__init__("car_gui_node")

        # 发布器
        self.pub_cmd = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)

        # 状态
        self.lat = None
        self.lon = None
        self.alt = None
        self.gps_status = -1
        self.fix_time = None
        self.latest_frame = None   # numpy BGR
        self.frame_time = None
        self.image_topic_active = ""
        self.ue_position = None    # parsed /R2UTopic_Pos payload
        self.ue_position_raw = ""
        self.ue_position_time = None
        self.ue_command_raw = ""
        self.ue_command_summary = "等待 UE 指令"
        self.ue_command_time = None
        self.imu_state = None
        self.odom_state = None
        self.topic_status = {}
        self.rosbridge_ok = False
        self.rosbridge_checked_at = None
        self._shutdown = threading.Event()
        self._last_mjpeg_warning = 0.0
        self._lock = threading.Lock()
        image_qos = qos_profile_sensor_data

        # 路径录制
        self.recording = False
        self.path_points = []       # [(lat, lon, alt, timestamp), ...]

        # 订阅 GPS
        self.create_subscription(NavSatFix, FIX_TOPIC, self._on_fix, 10)
        self.create_subscription(Imu, IMU_TOPIC, self._on_imu, image_qos)
        self.create_subscription(Odometry, ODOM_TOPIC, self._on_odom, image_qos)
        self.create_subscription(String, RTK_POS_TOPIC, self._on_ue_position, 10)
        self.create_subscription(String, UE_COMMAND_TOPIC, self._on_ue_command, 10)

        # 订阅图像。默认只挂配置话题，避免创建多余 DDS endpoint 拖慢首帧发现。
        for topic in IMAGE_TOPIC_CANDIDATES:
            self.create_subscription(
                Image,
                topic,
                lambda msg, image_topic=topic: self._on_image_raw(msg, image_topic),
                image_qos,
            )
        for topic in COMPRESSED_TOPIC_CANDIDATES:
            self.create_subscription(
                CompressedImage,
                topic,
                lambda msg, image_topic=topic: self._on_image_compressed(msg, image_topic),
                image_qos,
            )
        if CAMERA_GUI_SOURCE in ("auto", "mjpeg", "http"):
            self._mjpeg_thread = threading.Thread(target=self._mjpeg_loop, daemon=True)
            self._mjpeg_thread.start()
        else:
            self._mjpeg_thread = None
        self.create_timer(1.0, self._refresh_runtime_status)

    # ── 回调 ──────────────────────────────────────────────────────────────────
    def _on_fix(self, msg: NavSatFix):
        with self._lock:
            self.lat = msg.latitude
            self.lon = msg.longitude
            self.alt = msg.altitude
            self.gps_status = msg.status.status
            self.fix_time = time.time()
            if self.recording and self.lat is not None:
                self.path_points.append((self.lat, self.lon, self.alt, time.time()))

    def _on_imu(self, msg: Imu):
        now = time.time()
        q = msg.orientation
        raw_yaw = raw_yaw_deg_from_quaternion(q)
        av = msg.angular_velocity
        la = msg.linear_acceleration
        with self._lock:
            self.imu_state = {
                "time": now,
                "frame_id": msg.header.frame_id,
                "raw_yaw_deg": raw_yaw,
                "yaw_deg": calibrated_yaw_deg(raw_yaw),
                "heading_offset_deg": VEHICLE_HEADING_OFFSET_DEG,
                "angular_velocity": {
                    "x": finite_or_none(av.x),
                    "y": finite_or_none(av.y),
                    "z": finite_or_none(av.z),
                },
                "linear_acceleration": {
                    "x": finite_or_none(la.x),
                    "y": finite_or_none(la.y),
                    "z": finite_or_none(la.z),
                },
            }

    def _on_odom(self, msg: Odometry):
        now = time.time()
        q = msg.pose.pose.orientation
        raw_yaw = raw_yaw_deg_from_quaternion(q)
        lin = msg.twist.twist.linear
        ang = msg.twist.twist.angular
        vx = finite_or_none(lin.x)
        vy = finite_or_none(lin.y)
        vz = finite_or_none(lin.z)
        speed = None
        if vx is not None and vy is not None:
            speed = math.hypot(vx, vy)
        with self._lock:
            self.odom_state = {
                "time": now,
                "frame_id": msg.header.frame_id,
                "child_frame_id": msg.child_frame_id,
                "raw_yaw_deg": raw_yaw,
                "yaw_deg": calibrated_yaw_deg(raw_yaw),
                "heading_offset_deg": VEHICLE_HEADING_OFFSET_DEG,
                "speed_mps": speed,
                "linear_velocity": {"x": vx, "y": vy, "z": vz},
                "angular_velocity": {
                    "x": finite_or_none(ang.x),
                    "y": finite_or_none(ang.y),
                    "z": finite_or_none(ang.z),
                },
            }

    def _on_image_raw(self, msg: Image, topic: str):
        frame = self._decode_raw(msg)
        if frame is not None:
            self._store_frame(frame, topic)

    def _on_image_compressed(self, msg: CompressedImage, topic: str):
        data = np.frombuffer(msg.data, dtype=np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is not None:
            self._store_frame(frame, topic)

    def _store_frame(self, frame, source: str):
        with self._lock:
            self.latest_frame = frame
            self.frame_time = time.time()
            self.image_topic_active = source

    def _mjpeg_loop(self):
        source_label = f"MJPEG {MJPEG_STREAM_URL}"
        while not self._shutdown.is_set():
            try:
                req = Request(MJPEG_STREAM_URL, headers={"User-Agent": "campusCar-GUI"})
                with urlopen(req, timeout=MJPEG_CONNECT_TIMEOUT_SEC) as stream:
                    buf = b""
                    while not self._shutdown.is_set():
                        chunk = stream.read(8192)
                        if not chunk:
                            break
                        buf += chunk
                        while True:
                            start = buf.find(b"\xff\xd8")
                            if start < 0:
                                if len(buf) > 4096:
                                    buf = buf[-4096:]
                                break
                            end = buf.find(b"\xff\xd9", start + 2)
                            if end < 0:
                                if start > 0:
                                    buf = buf[start:]
                                if len(buf) > MJPEG_BUFFER_LIMIT:
                                    buf = buf[-MJPEG_BUFFER_LIMIT:]
                                break
                            jpeg = buf[start:end + 2]
                            buf = buf[end + 2:]
                            frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                            if frame is not None:
                                self._store_frame(frame, source_label)
            except (OSError, URLError, TimeoutError, ValueError):
                now = time.time()
                if now - self._last_mjpeg_warning > 10.0:
                    self.get_logger().info(f"等待 MJPEG 图像源: {MJPEG_STREAM_URL}")
                    self._last_mjpeg_warning = now
            self._shutdown.wait(MJPEG_RECONNECT_SEC)

    def shutdown(self):
        self._shutdown.set()

    def _on_ue_position(self, msg: String):
        now = time.time()
        raw = msg.data
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        with self._lock:
            self.ue_position = payload
            self.ue_position_raw = raw
            self.ue_position_time = now

    def _on_ue_command(self, msg: String):
        now = time.time()
        raw = msg.data
        summary = self._summarize_ue_command(raw)
        with self._lock:
            self.ue_command_raw = raw
            self.ue_command_summary = summary
            self.ue_command_time = now

    def _summarize_ue_command(self, raw: str) -> str:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return "非法 JSON"

        cmd_id = data.get("commandId", "--")
        cmd_type = data.get("commandType", "--")
        robot_id = data.get("RobotId", "--")
        params = data.get("commandParams", {}) if isinstance(data.get("commandParams"), dict) else {}
        dest = params.get("destination", "--")
        speed = params.get("speed", "--")

        if isinstance(dest, dict):
            x = dest.get("x", "--")
            y = dest.get("y", "--")
            dest_text = f"坐标 x={x}, y={y}"
        else:
            dest_text = str(dest)
        return f"{cmd_id} | {cmd_type} | {robot_id} | {dest_text} | speed={speed}"

    def _refresh_runtime_status(self):
        now = time.time()
        topic_status = {}
        for topic, _label in TOPICS_TO_MONITOR:
            try:
                topic_status[topic] = {
                    "publishers": self.count_publishers(topic),
                    "subscribers": self.count_subscribers(topic),
                }
            except Exception:
                topic_status[topic] = {"publishers": 0, "subscribers": 0}

        try:
            with socket.create_connection(("127.0.0.1", ROSBRIDGE_PORT), timeout=0.15):
                rosbridge_ok = True
        except OSError:
            rosbridge_ok = False

        with self._lock:
            self.topic_status = topic_status
            self.rosbridge_ok = rosbridge_ok
            self.rosbridge_checked_at = now

    def _decode_raw(self, msg: Image):
        enc = msg.encoding.lower()
        data = np.frombuffer(msg.data, dtype=np.uint8)
        try:
            if enc in ("rgb8",):
                img = data.reshape((msg.height, msg.width, 3))
                return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            elif enc in ("bgr8",):
                return data.reshape((msg.height, msg.width, 3))
            elif enc == "mono8":
                gray = data.reshape((msg.height, msg.width))
                return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            elif enc in ("yuv422", "yuv422_yuy2", "yuyv"):
                img = data.reshape((msg.height, msg.width, 2))
                return cv2.cvtColor(img, cv2.COLOR_YUV2BGR_YUYV)
            else:
                img = data.reshape((msg.height, msg.width, -1))
                return img
        except Exception:
            return None

    # ── 控制 ──────────────────────────────────────────────────────────────────
    def send_cmd(self, linear: float, angular: float):
        linear, angular = shape_twist_for_base(linear, angular)
        msg = Twist()
        msg.linear.x = linear
        msg.angular.z = angular
        self.pub_cmd.publish(msg)

    def stop(self):
        self.send_cmd(0.0, 0.0)

    # ── 录制 ──────────────────────────────────────────────────────────────────
    def start_recording(self):
        self.path_points = []
        self.recording = True

    def stop_recording(self) -> Path | None:
        self.recording = False
        if not self.path_points:
            return None
        RECORD_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = RECORD_DIR / f"path_{ts}.json"
        data = {
            "recorded_at": ts,
            "points": [
                {"lat": p[0], "lon": p[1], "alt": p[2], "t": p[3]}
                for p in self.path_points
            ]
        }
        out.write_text(json.dumps(data, indent=2))
        return out

    # ── 读取状态（线程安全）──────────────────────────────────────────────────
    def get_gps(self):
        with self._lock:
            return self.lat, self.lon, self.alt, self.gps_status, self.fix_time

    def get_frame(self):
        with self._lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def get_path_count(self):
        with self._lock:
            return len(self.path_points)

    def get_ue_monitor(self):
        with self._lock:
            return {
                "position": dict(self.ue_position) if isinstance(self.ue_position, dict) else self.ue_position,
                "position_raw": self.ue_position_raw,
                "position_time": self.ue_position_time,
                "command_raw": self.ue_command_raw,
                "command_summary": self.ue_command_summary,
                "command_time": self.ue_command_time,
                "topic_status": {k: dict(v) for k, v in self.topic_status.items()},
                "rosbridge_ok": self.rosbridge_ok,
                "rosbridge_checked_at": self.rosbridge_checked_at,
                "image_topic_active": self.image_topic_active,
                "frame_time": self.frame_time,
            }

    def get_vehicle_state(self):
        with self._lock:
            return {
                "imu": dict(self.imu_state) if isinstance(self.imu_state, dict) else None,
                "odom": dict(self.odom_state) if isinstance(self.odom_state, dict) else None,
            }


# ══════════════════════════════════════════════════════════════════════════════
# GUI 主窗口
# ══════════════════════════════════════════════════════════════════════════════
class CarGUI:
    def __init__(self, root: tk.Tk, node: CarNode):
        self.root = root
        self.node = node

        # 键盘控制状态：WASD 负责输入手感，底层仍发布 Twist(linear.x, angular.z)
        self._keys_held: set[str] = set()
        self._release_jobs = {}
        self._button_motion = None
        self._current_linear = 0.0
        self._current_angular = 0.0
        self._last_raw_display = None
        self._camera_view_size = (0, 0)

        # 录制状态
        self._recording = False

        self._build_ui()
        self._bind_keys()
        self._schedule_update()

    # ── 构建界面 ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.root.title("小车控制台")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(1180, 720)

        # ── 顶部标题栏 ────────────────────────────────────────────────────────
        title_bar = tk.Frame(self.root, bg=BG, pady=6)
        title_bar.pack(fill=tk.X, padx=12)
        tk.Label(title_bar, text="小车控制台", font=FONT_TITLE,
                 bg=BG, fg=ACCENT).pack(side=tk.LEFT)
        self.lbl_ros = tk.Label(title_bar, text="ROS2", font=FONT_NORMAL,
                                bg=BG, fg=GREEN)
        self.lbl_ros.pack(side=tk.RIGHT, padx=4)

        # ── 主体：左侧视频/控制 + 右侧联调信息 ────────────────────────────────
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        left = tk.Frame(body, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = tk.Frame(body, bg=BG, width=440)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right.pack_propagate(False)

        # ── 摄像头画面 ────────────────────────────────────────────────────────
        self.cam_frame = tk.Frame(left, bg=BG2, bd=0, highlightthickness=1,
                                  highlightbackground=SUBTEXT)
        self.cam_frame.pack(fill=tk.BOTH, expand=True)
        self.cam_frame.pack_propagate(False)

        self.cam_label = tk.Label(self.cam_frame, bg="#000000",
                                  text="等待摄像头...", fg=SUBTEXT,
                                  font=FONT_NORMAL, width=1, height=1)
        self.cam_label.pack(fill=tk.BOTH, expand=True)
        self.cam_frame.bind("<Configure>", self._on_camera_area_configure)

        left_bottom = tk.Frame(left, bg=BG)
        left_bottom.pack(fill=tk.X, pady=(10, 0))

        # ── 键盘控制面板 ──────────────────────────────────────────────────────
        ctrl_panel = self._card(left_bottom, "键盘控制", side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        ctrl_content = tk.Frame(ctrl_panel, bg=BG2)
        ctrl_content.pack(fill=tk.X)

        speed_box = tk.Frame(ctrl_content, bg=BG2)
        speed_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        speed_row = tk.Frame(speed_box, bg=BG2)
        speed_row.pack(fill=tk.X)
        tk.Label(speed_row, text="线速", bg=BG2, fg=SUBTEXT,
                 font=FONT_SMALL, width=5, anchor=tk.W).pack(side=tk.LEFT)
        self.speed_var = tk.DoubleVar(value=LINEAR_SPEED)
        spd_scale = tk.Scale(speed_row, from_=0.05, to=1.0, resolution=0.05,
                 orient=tk.HORIZONTAL, variable=self.speed_var,
                 bg=BG2, fg=TEXT, troughcolor=BG, highlightthickness=0,
                 length=180, takefocus=0)
        spd_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        spd_scale.bind("<ButtonRelease-1>", lambda e: self.root.focus_set())

        ang_row = tk.Frame(speed_box, bg=BG2)
        ang_row.pack(fill=tk.X, pady=(2, 0))
        tk.Label(ang_row, text="角速", bg=BG2, fg=SUBTEXT,
                 font=FONT_SMALL, width=5, anchor=tk.W).pack(side=tk.LEFT)
        self.ang_var = tk.DoubleVar(value=ANGULAR_SPEED)
        ang_scale = tk.Scale(ang_row, from_=0.1, to=2.0, resolution=0.1,
                 orient=tk.HORIZONTAL, variable=self.ang_var,
                 bg=BG2, fg=TEXT, troughcolor=BG, highlightthickness=0,
                 length=180, takefocus=0)
        ang_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ang_scale.bind("<ButtonRelease-1>", lambda e: self.root.focus_set())

        self.lbl_cmd = tk.Label(speed_box, text="停止", bg=BG2, fg=SUBTEXT,
                                font=FONT_SMALL, anchor=tk.W)
        self.lbl_cmd.pack(fill=tk.X, pady=(2, 0))
        self.lbl_key_help = tk.Label(
            speed_box,
            text="WASD/方向键按住移动，组合键斜向；松开停止，空格/X急停",
            bg=BG2, fg=SUBTEXT, font=FONT_SMALL,
            wraplength=360, justify=tk.LEFT,
        )
        self.lbl_key_help.pack(fill=tk.X, pady=(2, 0))

        # ── 录制面板 ──────────────────────────────────────────────────────────
        rec_panel = self._card(left_bottom, "路径录制", side=tk.RIGHT, fill=tk.Y)

        self.btn_record = tk.Button(
            rec_panel, text="开始录制", font=FONT_BTN,
            bg=GREEN, fg=BG, activebackground="#7ec87a", relief=tk.FLAT,
            padx=18, pady=8, cursor="hand2", command=self._toggle_record)
        self.btn_record.pack(fill=tk.X)

        self.lbl_rec_info = tk.Label(rec_panel, text="未录制", bg=BG2,
                                     fg=SUBTEXT, font=FONT_SMALL, width=18,
                                     anchor=tk.W)
        self.lbl_rec_info.pack(anchor=tk.W, pady=(6, 0))

        # ── 连接状态面板 ──────────────────────────────────────────────────────
        conn_panel = self._card(right, "UE 连接状态", fill=tk.X, pady=(0, 5))

        self.lbl_rosbridge = self._kv(conn_panel, "rosbridge", label_width=10)
        self.lbl_ue_activity = self._kv(conn_panel, "UE活跃", label_width=10)
        self.lbl_graph_time = self._kv(conn_panel, "刷新", label_width=10)

        # ── 话题状态面板 ──────────────────────────────────────────────────────
        topics_panel = self._card(right, "UE 相关话题", fill=tk.X, pady=(0, 5))
        self.topic_labels = {}
        for topic, label in TOPICS_TO_MONITOR:
            self.topic_labels[topic] = self._kv(topics_panel, label, label_width=8)

        # ── 底盘状态面板 ──────────────────────────────────────────────────────
        vehicle_panel = self._card(right, "底盘状态", fill=tk.X, pady=(0, 5))
        vehicle_body = tk.Frame(vehicle_panel, bg=BG2)
        vehicle_body.pack(fill=tk.X)
        self.heading_canvas = tk.Canvas(
            vehicle_body, width=74, height=74, bg=BG2,
            highlightthickness=0, bd=0,
        )
        self.heading_canvas.pack(side=tk.LEFT, padx=(0, 8))
        vehicle_values = tk.Frame(vehicle_body, bg=BG2)
        vehicle_values.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_vehicle_heading = self._kv(vehicle_values, "朝向", label_width=8)
        self.lbl_vehicle_speed = self._kv(vehicle_values, "速度", label_width=8)
        self.lbl_vehicle_yaw_rate = self._kv(vehicle_values, "角速度", label_width=8)
        self.lbl_vehicle_accel = self._kv(vehicle_values, "加速度", label_width=8)
        self.lbl_vehicle_imu_time = self._kv(vehicle_values, "IMU", label_width=8)
        self.lbl_vehicle_odom_time = self._kv(vehicle_values, "里程计", label_width=8)
        self.lbl_vehicle_offset = self._kv(vehicle_values, "校准", label_width=8)
        self.btn_heading_north = tk.Button(
            vehicle_values, text="设为正北", font=FONT_SMALL,
            bg=ACCENT, fg=BG, activebackground="#a6c8ff",
            relief=tk.FLAT, cursor="hand2",
            command=self._calibrate_heading_to_north,
        )
        self.btn_heading_north.pack(fill=tk.X, pady=(3, 0))
        self._draw_heading(None)

        # ── 坐标信息面板 ──────────────────────────────────────────────────────
        gps_panel = self._card(right, "实时经纬度", fill=tk.X, pady=(0, 5))

        tk.Label(gps_panel, text="/fix 原始定位", bg=BG2, fg=ACCENT,
                 font=FONT_SMALL).pack(anchor=tk.W, pady=(0, 2))
        self.lbl_lat  = self._kv(gps_panel, "纬度", label_width=8)
        self.lbl_lon  = self._kv(gps_panel, "经度", label_width=8)
        self.lbl_alt  = self._kv(gps_panel, "海拔", label_width=8)
        self.lbl_gps_status = self._kv(gps_panel, "状态", label_width=8)
        self.lbl_fix_time = self._kv(gps_panel, "更新时间", label_width=8)

        tk.Label(gps_panel, text="/R2UTopic_Pos 发给 UE", bg=BG2, fg=ACCENT,
                 font=FONT_SMALL).pack(anchor=tk.W, pady=(8, 2))
        self.lbl_ue_lat = self._kv(gps_panel, "纬度", label_width=8)
        self.lbl_ue_lon = self._kv(gps_panel, "经度", label_width=8)
        self.lbl_ue_alt = self._kv(gps_panel, "海拔", label_width=8)
        self.lbl_ue_pos_hold = self._kv(gps_panel, "坐标源", label_width=8)
        self.lbl_ue_pos_time = self._kv(gps_panel, "更新时间", label_width=8)

        # ── UE 消息面板 ──────────────────────────────────────────────────────
        msg_panel = self._card(right, "UE 最近发送", fill=tk.BOTH, expand=True)

        self.lbl_ue_cmd_time = self._kv(msg_panel, "接收时间", label_width=8)
        self.lbl_ue_cmd_summary = tk.Label(
            msg_panel, text="等待 UE 指令", bg=BG2, fg=SUBTEXT,
            font=FONT_MONO, anchor=tk.W, justify=tk.LEFT, wraplength=390,
        )
        self.lbl_ue_cmd_summary.pack(fill=tk.X, pady=(4, 4))
        ue_raw_frame = tk.Frame(msg_panel, bg=PANEL2)
        ue_raw_frame.pack(fill=tk.BOTH, expand=True)
        self.txt_ue_cmd_raw = tk.Text(
            ue_raw_frame, height=9, bg=PANEL2, fg=TEXT, insertbackground=TEXT,
            relief=tk.FLAT, font=FONT_MONO, wrap=tk.WORD, padx=8, pady=6,
            takefocus=0,
        )
        ue_raw_scroll = tk.Scrollbar(
            ue_raw_frame, orient=tk.VERTICAL, command=self.txt_ue_cmd_raw.yview,
            relief=tk.FLAT, bg=BG2, troughcolor=PANEL2,
        )
        self.txt_ue_cmd_raw.configure(yscrollcommand=ue_raw_scroll.set)
        ue_raw_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_ue_cmd_raw.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.txt_ue_cmd_raw.insert("1.0", "等待 UE 发送消息...")
        self.txt_ue_cmd_raw.configure(state=tk.DISABLED)

        # ── 底部状态栏 ────────────────────────────────────────────────────────
        status_bar = tk.Frame(self.root, bg=BG2, pady=4)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.lbl_status = tk.Label(status_bar, text="就绪  |  WASD/方向键移动  |  组合键转弯  |  空格/X停止",
                                   bg=BG2, fg=SUBTEXT, font=FONT_SMALL)
        self.lbl_status.pack(side=tk.LEFT, padx=10)

    def _card(self, parent, title: str, **pack_options) -> tk.Frame:
        """带标题的卡片容器"""
        outer = tk.Frame(parent, bg=BG)
        tk.Label(outer, text=title, bg=BG, fg=ACCENT,
                 font=FONT_CARD).pack(anchor=tk.W, pady=(0, 3))
        inner = tk.Frame(outer, bg=BG2, padx=8, pady=6,
                         highlightthickness=1, highlightbackground=SUBTEXT)
        inner.pack(fill=tk.BOTH, expand=True)
        if pack_options:
            outer.pack(**pack_options)
        return inner

    def _kv(self, parent, label: str, label_width: int = 7) -> tk.Label:
        """键值行，返回值标签"""
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill=tk.X)
        tk.Label(row, text=label, bg=BG2, fg=SUBTEXT,
                 font=FONT_SMALL, width=label_width, anchor=tk.W).pack(side=tk.LEFT)
        val = tk.Label(row, text="--", bg=BG2, fg=TEXT,
                       font=FONT_MONO, anchor=tk.W, justify=tk.LEFT,
                       wraplength=330)
        val.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return val

    def _build_dpad(self, parent):
        """方向键示意图"""
        dpad = tk.Frame(parent, bg=BG2)
        dpad.pack(side=tk.LEFT, pady=(4, 0))

        btn_cfg = dict(width=3, height=1, relief=tk.FLAT, font=FONT_NORMAL,
                       bg=BG, fg=TEXT, activebackground=ACCENT, cursor="hand2")

        layout = [
            ("W+A", 1.0, 1.0, 0, 0), ("W", 1.0, 0.0, 0, 1), ("W+D", 1.0, -1.0, 0, 2),
            ("A", 0.0, 1.0, 1, 0), ("X", 0.0, 0.0, 1, 1), ("D", 0.0, -1.0, 1, 2),
            ("S+A", -1.0, 1.0, 2, 0), ("S", -1.0, 0.0, 2, 1), ("S+D", -1.0, -1.0, 2, 2),
        ]
        self._button_motion = None
        for label, lin_sign, ang_sign, row, col in layout:
            if label == "X":
                button = tk.Button(
                    dpad, text="X", width=5, height=1,
                    relief=tk.FLAT, font=FONT_NORMAL,
                    bg=RED, fg=BG, activebackground="#e07090",
                    cursor="hand2", command=self._stop_car,
                )
            else:
                button = tk.Button(
                    dpad, text=label, width=5, height=1,
                    relief=tk.FLAT, font=FONT_NORMAL,
                    bg=BG, fg=TEXT, activebackground=ACCENT, cursor="hand2",
                )
                button.bind("<ButtonPress-1>", lambda _e, l=lin_sign, a=ang_sign: self._start_button_motion(l, a))
                button.bind("<ButtonRelease-1>", self._stop_button_motion)
                button.bind("<Leave>", self._stop_button_motion)
            button.grid(row=row, column=col, padx=2, pady=2)

    # ── 键盘绑定：WASD 手感，Twist 发布逻辑沿用官方 teleop 思路 ──────────────
    def _bind_keys(self):
        self.root.bind_all("<KeyPress>", self._on_key_press)
        self.root.bind_all("<KeyRelease>", self._on_key_release)
        self.root.bind_all("<FocusOut>", self._on_focus_out)
        self.root.after(200, self._focus_keyboard)
        self._cmd_loop()

    def _focus_keyboard(self):
        self.root.focus_force()
        self.lbl_status.config(text="键盘控制已就绪  |  WASD/方向键按住移动  |  空格/X停车")

    def _normalize_key(self, event):
        key = event.keysym
        char = event.char
        if char:
            return char.lower()
        aliases = {
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
            "space": "space",
        }
        lowered = key.lower()
        if lowered in aliases:
            return aliases[lowered]
        if len(lowered) == 1:
            return lowered
        return ""

    def _on_key_press(self, event):
        key = self._normalize_key(event)
        if key in ("space", "x"):
            self._stop_car()
            return "break"

        if key in SPEED_BINDINGS:
            self._scale_speed(*SPEED_BINDINGS[key])
            return "break"

        if key in MOVE_KEYS:
            self._cancel_release_job(key)
            self._keys_held.add(key)
            self._apply_held_keys()
            return "break"

    def _on_key_release(self, event):
        key = self._normalize_key(event)
        if key in MOVE_KEYS:
            self._schedule_release(key)
            return "break"

    def _on_focus_out(self, _event):
        self._stop_car()

    def _cancel_release_job(self, key: str):
        job = self._release_jobs.pop(key, None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass

    def _schedule_release(self, key: str):
        self._cancel_release_job(key)
        self._release_jobs[key] = self.root.after(
            KEY_RELEASE_DEBOUNCE_MS,
            lambda k=key: self._finish_release(k),
        )

    def _finish_release(self, key: str):
        self._release_jobs.pop(key, None)
        self._keys_held.discard(key)
        self._apply_held_keys()

    def _cmd_loop(self):
        if self._button_motion is not None:
            self._set_motion(*self._button_motion)
        elif self._keys_held:
            self._apply_held_keys()
        self.root.after(CMD_REPEAT_MS, self._cmd_loop)

    def _scale_speed(self, linear_factor: float, angular_factor: float):
        self.speed_var.set(round(max(0.0, min(1.0, self.speed_var.get() * linear_factor)), 2))
        self.ang_var.set(round(max(0.0, min(2.0, self.ang_var.get() * angular_factor)), 2))
        self.root.focus_set()
        self.lbl_status.config(
            text=f"当前速度  线速 {self.speed_var.get():.2f} m/s  角速 {self.ang_var.get():.2f} rad/s"
        )
        if self._current_linear != 0.0 or self._current_angular != 0.0:
            self._current_linear = math.copysign(self.speed_var.get(), self._current_linear) \
                if self._current_linear != 0.0 else 0.0
            self._current_angular = math.copysign(self.ang_var.get(), self._current_angular) \
                if self._current_angular != 0.0 else 0.0
            self._publish_current_cmd()

    def _apply_held_keys(self):
        if self._button_motion is not None:
            return

        lin_sign = 0.0
        ang_sign = 0.0
        if "w" in self._keys_held or "up" in self._keys_held:
            lin_sign += 1.0
        if "s" in self._keys_held or "down" in self._keys_held:
            lin_sign -= 1.0
        if "a" in self._keys_held or "left" in self._keys_held:
            ang_sign += 1.0
        if "d" in self._keys_held or "right" in self._keys_held:
            ang_sign -= 1.0
        self._set_motion(
            max(-1.0, min(1.0, lin_sign)),
            max(-1.0, min(1.0, ang_sign)),
        )

    def _start_button_motion(self, lin_sign: float, ang_sign: float):
        self._button_motion = (lin_sign, ang_sign)
        self._keys_held.clear()
        self._set_motion(lin_sign, ang_sign)
        return "break"

    def _stop_button_motion(self, _event=None):
        if self._button_motion is not None:
            self._button_motion = None
            self._stop_car()
        return "break"

    def _set_motion(self, lin_sign: float, ang_sign: float):
        self._current_linear = lin_sign * self.speed_var.get()
        self._current_angular = ang_sign * self.ang_var.get()
        self._publish_current_cmd()

    def _publish_current_cmd(self):
        lin = self._current_linear
        ang = self._current_angular
        self.node.send_cmd(lin, ang)
        dirs = []
        if lin > 0: dirs.append("前进")
        elif lin < 0: dirs.append("后退")
        if ang > 0: dirs.append("左转")
        elif ang < 0: dirs.append("右转")
        self.lbl_cmd.config(text=" + ".join(dirs) if dirs else "停止",
                            fg=YELLOW if dirs else SUBTEXT)

    def _stop_car(self):
        for key in list(self._release_jobs):
            self._cancel_release_job(key)
        self._keys_held.clear()
        self._button_motion = None
        self._current_linear = 0.0
        self._current_angular = 0.0
        self.node.stop()
        self.lbl_cmd.config(text="停止", fg=SUBTEXT)

    # ── 录制 ──────────────────────────────────────────────────────────────────
    def _toggle_record(self):
        if not self._recording:
            self._recording = True
            self.node.start_recording()
            self.btn_record.config(text="停止录制", bg=RED, fg=BG,
                                   activebackground="#e07090")
            self.lbl_rec_info.config(text="录制中...", fg=RED)
        else:
            self._recording = False
            saved = self.node.stop_recording()
            self.btn_record.config(text="开始录制", bg=GREEN, fg=BG,
                                   activebackground="#7ec87a")
            if saved:
                self.lbl_rec_info.config(
                    text=f"已保存: {saved.name}", fg=GREEN)
                self.lbl_status.config(text=f"路径已保存 → {saved}")
            else:
                self.lbl_rec_info.config(text="无数据（GPS未就绪）", fg=YELLOW)

    # ── 定时刷新 ──────────────────────────────────────────────────────────────
    def _schedule_update(self):
        self._update()
        self.root.after(80, self._schedule_update)   # ~12 fps UI 刷新

    def _update(self):
        self._update_gps()
        self._update_vehicle_state()
        self._update_ue_monitor()
        self._update_camera()
        if self._recording:
            cnt = self.node.get_path_count()
            self.lbl_rec_info.config(text=f"录制中... {cnt} 个点")

    def _update_gps(self):
        lat, lon, alt, status, fix_time = self.node.get_gps()
        if lat is None:
            self.lbl_lat.config(text="等待 /fix", fg=SUBTEXT)
            self.lbl_lon.config(text="--", fg=SUBTEXT)
            self.lbl_alt.config(text="--", fg=SUBTEXT)
            self.lbl_gps_status.config(text="无信号", fg=RED)
            self.lbl_fix_time.config(text="--", fg=SUBTEXT)
        else:
            self.lbl_lat.config(text=f"{lat:.8f}°", fg=TEXT)
            self.lbl_lon.config(text=f"{lon:.8f}°", fg=TEXT)
            self.lbl_alt.config(text=f"{alt:.2f} m", fg=TEXT)
            if status >= 0:
                label = "RTK固定" if status == 2 else ("差分" if status == 1 else "单点")
                self.lbl_gps_status.config(text=f"● {label}", fg=GREEN)
            else:
                self.lbl_gps_status.config(text="● 无定位", fg=RED)
            self.lbl_fix_time.config(text=self._format_age(fix_time), fg=self._age_color(fix_time, 2.5, 8.0))

    def _format_age(self, ts):
        if ts is None:
            return "--"
        age = max(0.0, time.time() - ts)
        clock = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        return f"{clock} ({age:.1f}s前)"

    def _format_number(self, value, digits: int):
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return "--"

    def _age_color(self, ts, fresh_sec: float, stale_sec: float):
        if ts is None:
            return SUBTEXT
        age = time.time() - ts
        if age <= fresh_sec:
            return GREEN
        if age <= stale_sec:
            return YELLOW
        return RED

    def _format_position_hold(self, pos):
        vehicle = pos.get("vehicle") if isinstance(pos, dict) else None
        hold = vehicle.get("position_hold") if isinstance(vehicle, dict) else None
        if not isinstance(hold, dict):
            return "实时 RTK", SUBTEXT

        mode = hold.get("mode")
        speed = hold.get("speed_mps")
        cache_age = hold.get("cache_age_sec")
        if mode == "moving":
            speed_text = "--" if speed is None else f"{speed:.2f}m/s"
            return f"移动更新 {speed_text}", GREEN
        if mode == "stopped":
            age_text = "--" if cache_age is None else f"{cache_age:.1f}s"
            return f"静止锁定 缓存{age_text}", YELLOW
        if mode == "init":
            return "缓存初始化", GREEN
        if mode == "no_odom":
            return "无里程计 实时RTK", YELLOW
        if mode == "odom_stale":
            return "里程计过期 实时RTK", YELLOW
        if mode == "off":
            return "锁点关闭 实时RTK", SUBTEXT
        return str(mode or "实时 RTK"), SUBTEXT

    def _set_text_content(self, widget: tk.Text, text: str):
        if self._last_raw_display == text:
            return
        self._last_raw_display = text
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state=tk.DISABLED)

    def _format_signed(self, value, digits: int = 2, suffix: str = ""):
        if value is None:
            return "--"
        return f"{value:+.{digits}f}{suffix}"

    def _latest_raw_heading(self):
        state = self.node.get_vehicle_state()
        now = time.time()
        for source_key, source_name in (("imu", "IMU"), ("odom", "odom")):
            sample = state.get(source_key)
            if sample is None or now - sample.get("time", 0.0) > 3.0:
                continue
            raw_yaw = sample.get("raw_yaw_deg")
            if raw_yaw is not None:
                return raw_yaw, source_name
        return None, None

    def _calibrate_heading_to_north(self):
        raw_yaw, source = self._latest_raw_heading()
        if raw_yaw is None:
            messagebox.showwarning("无法校准", "等待 /imu 或 /odom 后再试。")
            return

        new_offset = normalize_offset_degrees(NORTH_YAW_ENU_DEG - raw_yaw)
        try:
            persist_vehicle_heading_offset(new_offset)
        except OSError as exc:
            messagebox.showerror("写入失败", f"无法写入 config/robot.env：{exc}")
            return

        set_vehicle_heading_offset(new_offset)
        self.lbl_status.config(
            text=f"已将当前 {source} 朝向设为正北，偏移 {new_offset:+.1f}°"
        )
        self.lbl_vehicle_offset.config(text=f"{new_offset:+.1f}°", fg=GREEN)

    def _draw_heading(self, yaw_deg):
        canvas = self.heading_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - 9
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                           outline=SUBTEXT, width=1)
        canvas.create_text(cx, cy - radius + 8, text="N", fill=SUBTEXT, font=FONT_SMALL)
        canvas.create_text(cx + radius - 8, cy, text="E", fill=SUBTEXT, font=FONT_SMALL)
        canvas.create_text(cx, cy + radius - 8, text="S", fill=SUBTEXT, font=FONT_SMALL)
        canvas.create_text(cx - radius + 8, cy, text="W", fill=SUBTEXT, font=FONT_SMALL)
        if yaw_deg is None:
            canvas.create_text(cx, cy, text="--", fill=SUBTEXT, font=FONT_NORMAL)
            return
        yaw = math.radians(yaw_deg)
        end_x = cx + math.cos(yaw) * (radius - 14)
        end_y = cy - math.sin(yaw) * (radius - 14)
        canvas.create_line(cx, cy, end_x, end_y, fill=ACCENT, width=4, arrow=tk.LAST)
        canvas.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=ACCENT, outline=ACCENT)

    def _update_vehicle_state(self):
        state = self.node.get_vehicle_state()
        imu = state.get("imu")
        odom = state.get("odom")
        now = time.time()

        heading = None
        heading_source = None
        if imu is not None and now - imu.get("time", 0.0) <= 3.0:
            heading = imu.get("yaw_deg")
            heading_source = "IMU"
        elif odom is not None and now - odom.get("time", 0.0) <= 3.0:
            heading = odom.get("yaw_deg")
            heading_source = "odom"
        self._draw_heading(heading)

        if heading is None:
            self.lbl_vehicle_heading.config(text="等待 /imu 或 /odom", fg=SUBTEXT)
        else:
            offset_note = " 校准" if abs(VEHICLE_HEADING_OFFSET_DEG) > 0.001 else ""
            self.lbl_vehicle_heading.config(
                text=f"{heading:.1f}° ENU{offset_note} ({heading_source})",
                fg=GREEN if heading_source == "IMU" else YELLOW,
            )
        self.lbl_vehicle_offset.config(
            text=f"{VEHICLE_HEADING_OFFSET_DEG:+.1f}°",
            fg=YELLOW if abs(VEHICLE_HEADING_OFFSET_DEG) > 0.001 else SUBTEXT,
        )

        if odom is None or odom.get("speed_mps") is None:
            self.lbl_vehicle_speed.config(text="等待 /odom", fg=SUBTEXT)
        else:
            vx = odom.get("linear_velocity", {}).get("x")
            vy = odom.get("linear_velocity", {}).get("y")
            self.lbl_vehicle_speed.config(
                text=f"{odom['speed_mps']:.2f} m/s  vx={self._format_signed(vx)} vy={self._format_signed(vy)}",
                fg=self._age_color(odom.get("time"), 1.5, 5.0),
            )

        yaw_rate = None
        yaw_rate_source = None
        if imu is not None:
            yaw_rate = imu.get("angular_velocity", {}).get("z")
            yaw_rate_source = "IMU"
        if yaw_rate is None and odom is not None:
            yaw_rate = odom.get("angular_velocity", {}).get("z")
            yaw_rate_source = "odom"
        if yaw_rate is None:
            self.lbl_vehicle_yaw_rate.config(text="等待角速度", fg=SUBTEXT)
        else:
            self.lbl_vehicle_yaw_rate.config(
                text=f"{self._format_signed(yaw_rate, 3)} rad/s ({yaw_rate_source})",
                fg=TEXT,
            )

        accel = imu.get("linear_acceleration", {}) if imu is not None else {}
        ax, ay, az = accel.get("x"), accel.get("y"), accel.get("z")
        if ax is None or ay is None or az is None:
            self.lbl_vehicle_accel.config(text="等待 /imu", fg=SUBTEXT)
        else:
            planar = math.hypot(ax, ay)
            self.lbl_vehicle_accel.config(
                text=f"xy={planar:.2f}  x={self._format_signed(ax)} y={self._format_signed(ay)} z={az:.2f} m/s²",
                fg=self._age_color(imu.get("time"), 1.5, 5.0),
            )

        self.lbl_vehicle_imu_time.config(
            text=self._format_age(imu.get("time") if imu is not None else None),
            fg=self._age_color(imu.get("time") if imu is not None else None, 1.5, 5.0),
        )
        self.lbl_vehicle_odom_time.config(
            text=self._format_age(odom.get("time") if odom is not None else None),
            fg=self._age_color(odom.get("time") if odom is not None else None, 1.5, 5.0),
        )

    def _update_ue_monitor(self):
        info = self.node.get_ue_monitor()
        pos = info["position"] if isinstance(info["position"], dict) else None
        now = time.time()

        if info["rosbridge_checked_at"] is None:
            self.lbl_rosbridge.config(text=f"检测中 :{ROSBRIDGE_PORT}", fg=SUBTEXT)
            self.lbl_ros.config(text="ROS2", fg=SUBTEXT)
        elif info["rosbridge_ok"]:
            self.lbl_rosbridge.config(text=f"● tcp://本机:{ROSBRIDGE_PORT} 可连接", fg=GREEN)
            self.lbl_ros.config(text="ROS2 / UE通道", fg=GREEN)
        else:
            self.lbl_rosbridge.config(text=f"● :{ROSBRIDGE_PORT} 未监听", fg=RED)
            self.lbl_ros.config(text="ROS2 / UE未连", fg=YELLOW)

        if info["command_time"] is None:
            self.lbl_ue_activity.config(text="等待 UE 发送消息", fg=SUBTEXT)
        else:
            age = now - info["command_time"]
            if age <= 2.0:
                self.lbl_ue_activity.config(text=f"● 活跃  {age:.1f}s前", fg=GREEN)
            elif age <= 30.0:
                self.lbl_ue_activity.config(text=f"● 空闲  {age:.1f}s前", fg=YELLOW)
            else:
                self.lbl_ue_activity.config(text=f"● 超时  {age:.1f}s前", fg=RED)
        self.lbl_graph_time.config(
            text=self._format_age(info["rosbridge_checked_at"]),
            fg=self._age_color(info["rosbridge_checked_at"], 2.5, 8.0),
        )

        topic_status = info["topic_status"]
        for topic, label_widget in self.topic_labels.items():
            counts = topic_status.get(topic, {"publishers": 0, "subscribers": 0})
            pubs = counts.get("publishers", 0)
            subs = counts.get("subscribers", 0)
            if topic == UE_COMMAND_TOPIC:
                state = "等待UE发布" if pubs == 0 and info["command_time"] is None else "可接收"
            elif topic == RTK_POS_TOPIC:
                if pubs == 0:
                    state = "等待坐标源"
                elif subs <= 1:
                    state = "输出中/等UE订阅"
                else:
                    state = "UE已订阅"
            elif topic == RTK_TEXT_TOPIC:
                state = "等待UE订阅" if subs == 0 else "UE已订阅"
            else:
                state = "在线" if pubs or subs else "未发现"
            color = GREEN if pubs or subs else SUBTEXT
            if topic == UE_COMMAND_TOPIC and info["command_time"] is not None:
                color = self._age_color(info["command_time"], 2.0, 30.0)
            label_widget.config(text=f"{topic}   pub:{pubs} sub:{subs}   {state}", fg=color)

        if pos is None:
            self.lbl_ue_lat.config(text="等待 /R2UTopic_Pos", fg=SUBTEXT)
            self.lbl_ue_lon.config(text="--", fg=SUBTEXT)
            self.lbl_ue_alt.config(text="--", fg=SUBTEXT)
            self.lbl_ue_pos_hold.config(text="--", fg=SUBTEXT)
            self.lbl_ue_pos_time.config(text=self._format_age(info["position_time"]), fg=SUBTEXT)
        else:
            self.lbl_ue_lat.config(text=self._format_number(pos.get("latitude"), 8), fg=TEXT)
            self.lbl_ue_lon.config(text=self._format_number(pos.get("longitude"), 8), fg=TEXT)
            self.lbl_ue_alt.config(text=f"{self._format_number(pos.get('altitude'), 2)} m", fg=TEXT)
            hold_text, hold_color = self._format_position_hold(pos)
            self.lbl_ue_pos_hold.config(text=hold_text, fg=hold_color)
            self.lbl_ue_pos_time.config(text=self._format_age(info["position_time"]), fg=GREEN)

        cmd_raw = info["command_raw"]
        if cmd_raw:
            self.lbl_ue_cmd_time.config(text=self._format_age(info["command_time"]), fg=GREEN)
            self.lbl_ue_cmd_summary.config(text=info["command_summary"], fg=YELLOW)
            self._set_text_content(self.txt_ue_cmd_raw, cmd_raw)
        else:
            self.lbl_ue_cmd_time.config(text="等待指令", fg=SUBTEXT)
            self.lbl_ue_cmd_summary.config(text="等待 UE 指令", fg=SUBTEXT)
            self._set_text_content(self.txt_ue_cmd_raw, "等待 UE 发送消息...")

    def _on_camera_area_configure(self, event):
        if event.width > 1 and event.height > 1:
            self._camera_view_size = (event.width, event.height)

    def _current_camera_view_size(self):
        w, h = self._camera_view_size
        if w < 100 or h < 100:
            w = self.cam_frame.winfo_width()
            h = self.cam_frame.winfo_height()
            if w > 1 and h > 1:
                self._camera_view_size = (w, h)
        return w, h

    def _update_camera(self):
        frame = self.node.get_frame()
        if frame is None:
            return
        w, h = self._current_camera_view_size()
        if w < 100 or h < 100:
            return
        fh, fw = frame.shape[:2]
        scale = min(w / fw, h / fh)
        nw, nh = max(1, int(fw * scale)), max(1, int(fh * scale))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        img = PILImage.fromarray(rgb)
        photo = ImageTk.PhotoImage(img)
        self.cam_label.config(image=photo, text="")
        self.cam_label._photo = photo


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════
def _spin_safe(node):
    """在后台线程中 spin，忽略 shutdown 时的异常"""
    from rclpy.executors import ExternalShutdownException
    try:
        rclpy.spin(node)
    except (ExternalShutdownException, Exception):
        pass


def main():
    # 1. tkinter 先初始化
    root = tk.Tk()
    root.geometry("1280x760")

    # 2. 预加载所有字体（必须在 rclpy.init 之前，否则 X11 字体缓存冲突导致段错误）
    global FONT_TITLE, FONT_NORMAL, FONT_SMALL, FONT_CARD, FONT_BTN, FONT_MONO
    FONT_TITLE  = tkfont.Font(family="Helvetica", size=16, weight="bold")
    FONT_NORMAL = tkfont.Font(family="Helvetica", size=12)
    FONT_SMALL  = tkfont.Font(family="Helvetica", size=9)
    FONT_CARD   = tkfont.Font(family="Helvetica", size=10, weight="bold")
    FONT_BTN    = tkfont.Font(family="Helvetica", size=11, weight="bold")
    FONT_MONO   = tkfont.Font(family="Courier",   size=10)

    # 3. rclpy 禁用信号处理，避免覆盖 X11
    rclpy.init(args=None, signal_handler_options=rclpy.SignalHandlerOptions.NO)
    node = CarNode()

    # 4. GUI 全部构建完毕后，再启动 spin 线程
    app = CarGUI(root, node)

    ros_thread = threading.Thread(target=_spin_safe, args=(node,), daemon=True)
    ros_thread.start()

    def on_close():
        node.shutdown()
        node.stop()
        root.destroy()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_close()


if __name__ == "__main__":
    main()
