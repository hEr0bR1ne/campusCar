#!/usr/bin/env python3
"""
campusCar web control console.

Serves a browser-based control panel and publishes manual commands to /cmd_vel.
The video panel reuses the existing MJPEG service, so this process stays light
enough to run as a boot service on the NUC.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import socket
import subprocess
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Imu, NavSatFix
from std_msgs.msg import String

from motion_profile import shape_twist_for_base


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config" / "robot.env"
LOG_DIR = PROJECT_ROOT / "data" / "logs"
RECORD_DIR = PROJECT_ROOT / "data" / "recorded_paths"


def load_project_env() -> None:
    if not CONFIG_FILE.exists():
        return

    command = f"set -a; source {shlex.quote(str(CONFIG_FILE))}; env -0"
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


def finite_or_none(value) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def normalize_degrees(value: float) -> float:
    return value % 360.0


def normalize_offset_degrees(value: float) -> float:
    return ((value + 180.0) % 360.0) - 180.0


def quaternion_to_yaw(q) -> float:
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


def raw_yaw_deg_from_quaternion(q) -> float:
    return normalize_degrees(math.degrees(quaternion_to_yaw(q)))


def persist_vehicle_heading_offset(value: float) -> None:
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


load_project_env()

CMD_VEL_TOPIC = env_str("CMD_VEL_TOPIC", "/cmd_vel")
FIX_TOPIC = env_str("FIX_TOPIC", "/fix")
IMU_TOPIC = env_str("IMU_TOPIC", "/imu")
ODOM_TOPIC = env_str("ODOM_TOPIC", "/odom")
IMAGE_TOPIC = env_str("IMAGE_TOPIC", "/camera/color/image_raw")
UE_COMMAND_TOPIC = env_str("UE_COMMAND_TOPIC", "/U2RTopic_Command")
RTK_POS_TOPIC = env_str("RTK_POS_TOPIC", "/R2UTopic_Pos")
RTK_TEXT_TOPIC = env_str("RTK_TEXT_TOPIC", "/R2UTopic_Text")
ROSBRIDGE_PORT = env_int("ROSBRIDGE_PORT", 9090)
MJPEG_PORT = env_int("MJPEG_PORT", 8080)
WEB_GUI_PORT = env_int("WEB_GUI_PORT", 8088)
WEB_CONTROL_RATE_HZ = env_float("WEB_CONTROL_RATE_HZ", 20.0)
WEB_CONTROL_TIMEOUT_SEC = env_float("WEB_CONTROL_TIMEOUT_SEC", 0.45)
DEFAULT_LINEAR_SPEED = env_float("DEFAULT_LINEAR_SPEED", 0.3)
DEFAULT_ANGULAR_SPEED = env_float("DEFAULT_ANGULAR_SPEED", 0.5)
MAX_LINEAR_SPEED = env_float("MAX_LINEAR_SPEED", 1.0)
MAX_ANGULAR_SPEED = env_float("MAX_ANGULAR_SPEED", 1.0)
VEHICLE_HEADING_OFFSET_DEG = env_float("VEHICLE_HEADING_OFFSET_DEG", 0.0)
NORTH_YAW_ENU_DEG = 90.0

UE_TOPIC_STATUS_ITEMS = [
    (UE_COMMAND_TOPIC, "指令入口", "command_in"),
    (RTK_POS_TOPIC, "坐标发给UE", "position_out"),
    (RTK_TEXT_TOPIC, "回复发给UE", "text_out"),
]

LOG_FILES = {
    "web_gui": LOG_DIR / "web_gui.log",
    "ue_bridge": LOG_DIR / "ue_bridge.log",
    "u2r_command": LOG_DIR / "u2r_command.log",
    "rosbridge": LOG_DIR / "rosbridge.log",
    "rtk_ue": LOG_DIR / "ue5_bridge.log",
    "camera": LOG_DIR / "camera.log",
    "mjpeg": LOG_DIR / "mjpeg_server.log",
}


def describe_ue_topic(
    *,
    topic: str,
    role: str,
    publishers: int,
    subscribers: int,
    command_age: float | None,
) -> tuple[str, str]:
    if role == "command_in":
        if subscribers <= 0:
            return "本机未监听，UE 指令进不来", "bad"
        if command_age is None:
            return "本机监听中，等待 UE 发送", "warn"
        if command_age <= 2.0:
            return f"刚收到 UE 指令 {command_age:.1f}s 前", "ok"
        if command_age <= 30.0:
            return f"最近收到过，当前空闲 {command_age:.1f}s", "warn"
        return f"长时间未收到 UE 指令 {command_age:.1f}s", "warn"

    if role == "position_out":
        if publishers <= 0:
            return "坐标桥未发布，UE 收不到位置", "bad"
        if subscribers <= 1:
            return "坐标发布中，等待 UE 订阅", "warn"
        return "坐标发布中，已有外部订阅", "ok"

    if role == "text_out":
        if publishers <= 0:
            return "回复节点未发布，UE 收不到文本", "bad"
        if subscribers <= 0:
            return "回复已准备，等待 UE 订阅", "warn"
        return "回复已准备，已有外部订阅", "ok"

    return ("在线" if publishers or subscribers else "未发现"), ("ok" if publishers or subscribers else "bad")


class WebControlNode(Node):
    def __init__(self):
        super().__init__("car_web_gui_node")
        self.pub_cmd = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)

        self._lock = threading.Lock()
        self._desired_linear = 0.0
        self._desired_angular = 0.0
        self._last_drive_time = 0.0
        self._drive_active = False

        self.heading_offset_deg = VEHICLE_HEADING_OFFSET_DEG
        self.lat = None
        self.lon = None
        self.alt = None
        self.gps_status = -1
        self.fix_time = None
        self.imu_state = None
        self.odom_state = None
        self.ue_position = None
        self.ue_position_raw = ""
        self.ue_position_time = None
        self.ue_command_raw = ""
        self.ue_command_summary = "等待 UE 指令"
        self.ue_command_time = None
        self.topic_status = {}
        self.rosbridge_ok = False
        self.rosbridge_checked_at = None

        self.recording = False
        self.path_points = []

        image_qos = qos_profile_sensor_data
        self.create_subscription(NavSatFix, FIX_TOPIC, self._on_fix, 10)
        self.create_subscription(Imu, IMU_TOPIC, self._on_imu, image_qos)
        self.create_subscription(Odometry, ODOM_TOPIC, self._on_odom, image_qos)
        self.create_subscription(String, RTK_POS_TOPIC, self._on_ue_position, 10)
        self.create_subscription(String, UE_COMMAND_TOPIC, self._on_ue_command, 10)

        control_period = 1.0 / max(WEB_CONTROL_RATE_HZ, 1.0)
        self.create_timer(control_period, self._control_timer)
        self.create_timer(1.0, self._refresh_runtime_status)

    def _calibrated_yaw(self, raw_yaw_deg: float) -> float:
        return normalize_degrees(raw_yaw_deg + self.heading_offset_deg)

    def _on_fix(self, msg: NavSatFix) -> None:
        now = time.time()
        with self._lock:
            self.lat = msg.latitude
            self.lon = msg.longitude
            self.alt = msg.altitude
            self.gps_status = msg.status.status
            self.fix_time = now
            if self.recording and self.lat is not None:
                self.path_points.append((self.lat, self.lon, self.alt, now))

    def _on_imu(self, msg: Imu) -> None:
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
                "yaw_deg": self._calibrated_yaw(raw_yaw),
                "heading_offset_deg": self.heading_offset_deg,
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

    def _on_odom(self, msg: Odometry) -> None:
        now = time.time()
        q = msg.pose.pose.orientation
        raw_yaw = raw_yaw_deg_from_quaternion(q)
        lin = msg.twist.twist.linear
        ang = msg.twist.twist.angular
        vx = finite_or_none(lin.x)
        vy = finite_or_none(lin.y)
        vz = finite_or_none(lin.z)
        speed = math.hypot(vx, vy) if vx is not None and vy is not None else None
        with self._lock:
            self.odom_state = {
                "time": now,
                "frame_id": msg.header.frame_id,
                "child_frame_id": msg.child_frame_id,
                "raw_yaw_deg": raw_yaw,
                "yaw_deg": self._calibrated_yaw(raw_yaw),
                "heading_offset_deg": self.heading_offset_deg,
                "speed_mps": speed,
                "linear_velocity": {"x": vx, "y": vy, "z": vz},
                "angular_velocity": {
                    "x": finite_or_none(ang.x),
                    "y": finite_or_none(ang.y),
                    "z": finite_or_none(ang.z),
                },
            }

    def _on_ue_position(self, msg: String) -> None:
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

    def _on_ue_command(self, msg: String) -> None:
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

    def _refresh_runtime_status(self) -> None:
        now = time.time()
        topic_status = {}
        for topic, _label, _role in UE_TOPIC_STATUS_ITEMS:
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

    def _publish_cmd(self, linear: float, angular: float) -> None:
        linear, angular = shape_twist_for_base(linear, angular)
        msg = Twist()
        msg.linear.x = float(linear)
        msg.angular.z = float(angular)
        self.pub_cmd.publish(msg)

    def _control_timer(self) -> None:
        now = time.monotonic()
        publish = None
        with self._lock:
            if self._drive_active and now - self._last_drive_time <= WEB_CONTROL_TIMEOUT_SEC:
                publish = (self._desired_linear, self._desired_angular)
            elif self._drive_active:
                self._drive_active = False
                self._desired_linear = 0.0
                self._desired_angular = 0.0
                publish = (0.0, 0.0)
        if publish is not None:
            self._publish_cmd(*publish)

    def set_drive(self, linear: float, angular: float) -> dict:
        linear = max(-MAX_LINEAR_SPEED, min(MAX_LINEAR_SPEED, float(linear)))
        angular = max(-MAX_ANGULAR_SPEED, min(MAX_ANGULAR_SPEED, float(angular)))
        with self._lock:
            self._desired_linear = linear
            self._desired_angular = angular
            self._last_drive_time = time.monotonic()
            self._drive_active = True
        self._publish_cmd(linear, angular)
        return self.get_control_state()

    def stop(self) -> dict:
        with self._lock:
            self._desired_linear = 0.0
            self._desired_angular = 0.0
            self._drive_active = False
            self._last_drive_time = time.monotonic()
        for _ in range(3):
            self._publish_cmd(0.0, 0.0)
            time.sleep(0.01)
        return self.get_control_state()

    def start_recording(self) -> dict:
        with self._lock:
            self.path_points = []
            self.recording = True
        return {"recording": True, "count": 0}

    def stop_recording(self) -> dict:
        with self._lock:
            points = list(self.path_points)
            self.recording = False
            self.path_points = []

        if not points:
            return {"recording": False, "count": 0, "saved": None}

        RECORD_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = RECORD_DIR / f"path_{ts}.json"
        data = {
            "recorded_at": ts,
            "points": [
                {"lat": p[0], "lon": p[1], "alt": p[2], "t": p[3]}
                for p in points
            ],
        }
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {"recording": False, "count": len(points), "saved": str(out)}

    def calibrate_heading_to_north(self) -> dict:
        raw_yaw, source = self._latest_raw_heading()
        if raw_yaw is None:
            raise RuntimeError("等待 /imu 或 /odom 后再校准")

        new_offset = normalize_offset_degrees(NORTH_YAW_ENU_DEG - raw_yaw)
        persist_vehicle_heading_offset(new_offset)
        with self._lock:
            self.heading_offset_deg = new_offset
            os.environ["VEHICLE_HEADING_OFFSET_DEG"] = f"{new_offset:.3f}"
        return {
            "offset_deg": new_offset,
            "raw_yaw_deg": raw_yaw,
            "source": source,
        }

    def _latest_raw_heading(self) -> tuple[float | None, str | None]:
        with self._lock:
            state = {
                "imu": dict(self.imu_state) if isinstance(self.imu_state, dict) else None,
                "odom": dict(self.odom_state) if isinstance(self.odom_state, dict) else None,
            }
        now = time.time()
        for source_key, source_name in (("imu", "IMU"), ("odom", "odom")):
            sample = state.get(source_key)
            if sample is None or now - sample.get("time", 0.0) > 3.0:
                continue
            raw_yaw = sample.get("raw_yaw_deg")
            if raw_yaw is not None:
                return raw_yaw, source_name
        return None, None

    def get_control_state(self) -> dict:
        now = time.monotonic()
        with self._lock:
            age = now - self._last_drive_time if self._last_drive_time else None
            active = self._drive_active and age is not None and age <= WEB_CONTROL_TIMEOUT_SEC
            return {
                "linear": self._desired_linear if active else 0.0,
                "angular": self._desired_angular if active else 0.0,
                "active": active,
                "age_sec": age,
                "timeout_sec": WEB_CONTROL_TIMEOUT_SEC,
            }

    def get_status(self) -> dict:
        now = time.time()
        with self._lock:
            gps = {
                "lat": self.lat,
                "lon": self.lon,
                "alt": self.alt,
                "status": self.gps_status,
                "time": self.fix_time,
                "age_sec": now - self.fix_time if self.fix_time else None,
            }
            ue_position = {
                "payload": dict(self.ue_position) if isinstance(self.ue_position, dict) else self.ue_position,
                "raw": self.ue_position_raw,
                "time": self.ue_position_time,
                "age_sec": now - self.ue_position_time if self.ue_position_time else None,
            }
            ue_command = {
                "raw": self.ue_command_raw,
                "summary": self.ue_command_summary,
                "time": self.ue_command_time,
                "age_sec": now - self.ue_command_time if self.ue_command_time else None,
            }
            vehicle = {
                "imu": dict(self.imu_state) if isinstance(self.imu_state, dict) else None,
                "odom": dict(self.odom_state) if isinstance(self.odom_state, dict) else None,
                "heading_offset_deg": self.heading_offset_deg,
            }
            topic_status = {k: dict(v) for k, v in self.topic_status.items()}
            rosbridge_ok = self.rosbridge_ok
            rosbridge_checked_at = self.rosbridge_checked_at
            recording = {
                "active": self.recording,
                "count": len(self.path_points),
            }

        ue_topics = []
        for topic, label, role in UE_TOPIC_STATUS_ITEMS:
            counts = topic_status.get(topic, {"publishers": 0, "subscribers": 0})
            pubs = counts.get("publishers", 0)
            subs = counts.get("subscribers", 0)
            status, tone = describe_ue_topic(
                topic=topic,
                role=role,
                publishers=pubs,
                subscribers=subs,
                command_age=ue_command["age_sec"],
            )
            ue_topics.append({
                "topic": topic,
                "label": label,
                "role": role,
                "publishers": pubs,
                "subscribers": subs,
                "status": status,
                "tone": tone,
            })

        return {
            "server_time": now,
            "project_root": str(PROJECT_ROOT),
            "config": {
                "cmd_vel_topic": CMD_VEL_TOPIC,
                "fix_topic": FIX_TOPIC,
                "imu_topic": IMU_TOPIC,
                "odom_topic": ODOM_TOPIC,
                "rtk_pos_topic": RTK_POS_TOPIC,
                "ue_command_topic": UE_COMMAND_TOPIC,
                "rtk_text_topic": RTK_TEXT_TOPIC,
                "rosbridge_port": ROSBRIDGE_PORT,
                "mjpeg_port": MJPEG_PORT,
                "web_gui_port": WEB_GUI_PORT,
                "default_linear": DEFAULT_LINEAR_SPEED,
                "default_angular": DEFAULT_ANGULAR_SPEED,
                "max_linear": MAX_LINEAR_SPEED,
                "max_angular": MAX_ANGULAR_SPEED,
            },
            "control": self.get_control_state(),
            "gps": gps,
            "vehicle": vehicle,
            "ue_position": ue_position,
            "ue_command": ue_command,
            "ue_topics": ue_topics,
            "topics": ue_topics,
            "rosbridge": {
                "ok": rosbridge_ok,
                "checked_at": rosbridge_checked_at,
                "age_sec": now - rosbridge_checked_at if rosbridge_checked_at else None,
            },
            "recording": recording,
        }


def tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    lines = max(1, min(lines, 300))
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            block_size = 4096
            data = b""
            while end > 0 and data.count(b"\n") <= lines:
                step = min(block_size, end)
                end -= step
                f.seek(end)
                data = f.read(step) + data
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def json_dumps(data) -> bytes:
    return json.dumps(
        json_safe(data),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def page_html() -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>campusCar 控制台</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #101214;
      --panel: #1a1d20;
      --panel-2: #22272b;
      --line: #343b40;
      --text: #eef3f4;
      --muted: #93a1a6;
      --accent: #2fb7a7;
      --warn: #e8a33a;
      --danger: #ef5b5b;
      --ok: #68c66f;
      --blue: #6aa8ff;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; background: var(--bg); color: var(--text); font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; letter-spacing: 0; }}
    body {{ overflow-x: hidden; }}
    button, input, select {{ font: inherit; }}
    .shell {{ min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }}
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; border-bottom: 1px solid var(--line); background: #15181a; }}
    h1 {{ margin: 0; font-size: 20px; font-weight: 700; }}
    .top-status {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }}
    .pill {{ border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; color: var(--muted); background: var(--panel); white-space: nowrap; }}
    .pill.ok {{ color: var(--ok); }}
    .pill.warn {{ color: var(--warn); }}
    .pill.bad {{ color: var(--danger); }}
    main {{ display: grid; grid-template-columns: minmax(0, 1fr) 430px; gap: 12px; padding: 12px; }}
    .left {{ min-width: 0; display: grid; grid-template-rows: minmax(360px, 1fr) auto; gap: 12px; }}
    .video {{ min-height: 360px; border: 1px solid var(--line); background: #050607; display: flex; align-items: center; justify-content: center; overflow: hidden; }}
    .video img {{ width: 100%; height: 100%; object-fit: contain; display: block; }}
    .controls {{ display: grid; grid-template-columns: 270px minmax(280px, 1fr) 220px; gap: 12px; align-items: stretch; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px; min-width: 0; }}
    .panel h2 {{ margin: 0 0 8px; color: var(--accent); font-size: 14px; font-weight: 700; }}
    .dpad {{ display: grid; grid-template-columns: repeat(3, 74px); grid-auto-rows: 54px; gap: 8px; justify-content: center; }}
    .drive-btn, .stop-btn, .cmd-btn {{ border: 1px solid var(--line); border-radius: 8px; background: var(--panel-2); color: var(--text); min-height: 44px; cursor: pointer; touch-action: none; }}
    .drive-btn:active, .drive-btn.active {{ background: #25443f; border-color: var(--accent); color: #dffdf8; }}
    .stop-btn {{ background: #3a1f22; border-color: #683033; color: #ffd7d7; }}
    .cmd-btn {{ padding: 8px 10px; background: #203038; border-color: #31505d; color: #d8eff7; }}
    .cmd-btn.primary {{ background: #173a36; border-color: var(--accent); color: #dffdf8; }}
    .cmd-btn.danger {{ background: #3a1f22; border-color: #683033; color: #ffd7d7; }}
    .sliders {{ display: grid; gap: 10px; }}
    .slider-row {{ display: grid; grid-template-columns: 54px 1fr 58px; gap: 8px; align-items: center; color: var(--muted); }}
    input[type="range"] {{ width: 100%; accent-color: var(--accent); }}
    .cmd-readout {{ margin-top: 8px; padding: 8px; border: 1px solid var(--line); border-radius: 6px; background: #141719; color: var(--muted); min-height: 38px; }}
    .actions {{ display: grid; gap: 8px; align-content: start; }}
    aside {{ min-width: 0; display: grid; gap: 8px; align-content: start; }}
    .kv {{ display: grid; grid-template-columns: 82px minmax(0, 1fr); gap: 8px; margin: 4px 0; align-items: start; }}
    .kv .k {{ color: var(--muted); }}
    .kv .v {{ overflow-wrap: anywhere; }}
    .fresh {{ color: var(--ok); }}
    .stale {{ color: var(--warn); }}
    .bad {{ color: var(--danger); }}
    .mono {{ font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; }}
    .topics {{ display: grid; gap: 5px; }}
    .topic {{ display: grid; grid-template-columns: 70px 1fr 82px; gap: 8px; padding: 5px 0; border-bottom: 1px solid #252b2f; }}
    .topic:last-child {{ border-bottom: 0; }}
    pre {{ margin: 0; padding: 8px; min-height: 92px; max-height: 170px; overflow: auto; white-space: pre-wrap; background: #111416; border: 1px solid var(--line); border-radius: 6px; color: #dbe5e7; }}
    .log-head {{ display: grid; grid-template-columns: 1fr auto; gap: 8px; margin-bottom: 8px; }}
    select {{ min-height: 34px; color: var(--text); background: var(--panel-2); border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; }}
    @media (max-width: 1100px) {{
      main {{ grid-template-columns: 1fr; }}
      aside {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 760px) {{
      header {{ align-items: flex-start; flex-direction: column; }}
      main {{ padding: 8px; gap: 8px; }}
      .left {{ grid-template-rows: minmax(250px, 45vh) auto; gap: 8px; }}
      .controls {{ grid-template-columns: 1fr; }}
      aside {{ grid-template-columns: 1fr; }}
      .dpad {{ grid-template-columns: repeat(3, minmax(64px, 1fr)); }}
      .topic {{ grid-template-columns: 62px 1fr 70px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <h1>campusCar 控制台</h1>
      <div class="top-status">
        <span id="rosbridgePill" class="pill">rosbridge</span>
        <span id="controlPill" class="pill">控制</span>
        <span id="gpsPill" class="pill">RTK</span>
        <span id="uePill" class="pill">UE</span>
      </div>
    </header>
    <main>
      <section class="left">
        <div class="video"><img id="video" alt="camera stream"></div>
        <div class="controls">
          <section class="panel">
            <h2>方向控制</h2>
            <div class="dpad">
              <button class="drive-btn" data-lin="1" data-ang="1">W+A</button>
              <button class="drive-btn" data-lin="1" data-ang="0">W</button>
              <button class="drive-btn" data-lin="1" data-ang="-1">W+D</button>
              <button class="drive-btn" data-lin="0" data-ang="1">A</button>
              <button class="stop-btn" id="stopBtn">STOP</button>
              <button class="drive-btn" data-lin="0" data-ang="-1">D</button>
              <button class="drive-btn" data-lin="-1" data-ang="1">S+A</button>
              <button class="drive-btn" data-lin="-1" data-ang="0">S</button>
              <button class="drive-btn" data-lin="-1" data-ang="-1">S+D</button>
            </div>
          </section>
          <section class="panel">
            <h2>速度</h2>
            <div class="sliders">
              <label class="slider-row"><span>线速</span><input id="linearSpeed" type="range" min="0.05" max="{MAX_LINEAR_SPEED:.2f}" step="0.05" value="{DEFAULT_LINEAR_SPEED:.2f}"><span id="linearValue">{DEFAULT_LINEAR_SPEED:.2f}</span></label>
              <label class="slider-row"><span>角速</span><input id="angularSpeed" type="range" min="0.10" max="{max(MAX_ANGULAR_SPEED, 0.1):.2f}" step="0.05" value="{DEFAULT_ANGULAR_SPEED:.2f}"><span id="angularValue">{DEFAULT_ANGULAR_SPEED:.2f}</span></label>
            </div>
            <div id="cmdReadout" class="cmd-readout mono">停止</div>
          </section>
          <section class="panel actions">
            <h2>操作</h2>
            <button class="cmd-btn danger" id="hardStopBtn">急停</button>
            <button class="cmd-btn primary" id="recordBtn">开始录制</button>
            <button class="cmd-btn" id="northBtn">设为正北</button>
          </section>
        </div>
      </section>
      <aside>
        <section class="panel">
          <h2>底盘状态</h2>
          <div class="kv"><span class="k">朝向</span><span id="heading" class="v">--</span></div>
          <div class="kv"><span class="k">速度</span><span id="speed" class="v">--</span></div>
          <div class="kv"><span class="k">角速度</span><span id="yawRate" class="v">--</span></div>
          <div class="kv"><span class="k">校准</span><span id="offset" class="v">--</span></div>
        </section>
        <section class="panel">
          <h2>实时经纬度</h2>
          <div class="kv"><span class="k">/fix 纬度</span><span id="fixLat" class="v mono">--</span></div>
          <div class="kv"><span class="k">/fix 经度</span><span id="fixLon" class="v mono">--</span></div>
          <div class="kv"><span class="k">状态</span><span id="fixStatus" class="v">--</span></div>
          <div class="kv"><span class="k">UE 纬度</span><span id="ueLat" class="v mono">--</span></div>
          <div class="kv"><span class="k">UE 经度</span><span id="ueLon" class="v mono">--</span></div>
          <div class="kv"><span class="k">坐标源</span><span id="holdMode" class="v">--</span></div>
        </section>
        <section class="panel">
          <h2>UE 最近发送</h2>
          <div class="kv"><span class="k">接收</span><span id="ueAge" class="v">--</span></div>
          <div id="ueSummary" class="mono">等待 UE 指令</div>
          <pre id="ueRaw">等待 UE 发送消息...</pre>
        </section>
        <section class="panel">
          <h2>UE 链路状态</h2>
          <div id="ueTopics" class="topics"></div>
        </section>
        <section class="panel">
          <div class="log-head">
            <h2>日志</h2>
            <select id="logSelect">
              <option value="ue_bridge">ue_bridge</option>
              <option value="u2r_command">u2r_command</option>
              <option value="rosbridge">rosbridge</option>
              <option value="rtk_ue">rtk_ue</option>
              <option value="web_gui">web_gui</option>
              <option value="camera">camera</option>
              <option value="mjpeg">mjpeg</option>
            </select>
          </div>
          <pre id="logBox">--</pre>
        </section>
      </aside>
    </main>
  </div>
  <script>
    const state = {{
      linearSpeed: {DEFAULT_LINEAR_SPEED:.2f},
      angularSpeed: {DEFAULT_ANGULAR_SPEED:.2f},
      active: null,
      timer: null,
      keys: new Set(),
      recording: false,
    }};
    const $ = (id) => document.getElementById(id);
    const videoUrl = `${{location.protocol}}//${{location.hostname}}:{MJPEG_PORT}/stream`;
    $("video").src = videoUrl;

    function clsByAge(age, fresh, stale) {{
      if (age === null || age === undefined) return "";
      if (age <= fresh) return "fresh";
      if (age <= stale) return "stale";
      return "bad";
    }}
    function fmtAge(age) {{
      if (age === null || age === undefined) return "--";
      return `${{Math.max(0, age).toFixed(1)}}s前`;
    }}
    function fmtNum(value, digits) {{
      const n = Number(value);
      return Number.isFinite(n) ? n.toFixed(digits) : "--";
    }}
    async function postJson(path, body={{}}) {{
      const res = await fetch(path, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(body),
      }});
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }}
    function drive(linearSign, angularSign) {{
      const linear = linearSign * state.linearSpeed;
      const angular = angularSign * state.angularSpeed;
      $("cmdReadout").textContent = `linear=${{linear.toFixed(2)}}  angular=${{angular.toFixed(2)}}`;
      postJson("/api/drive", {{ linear, angular }}).catch((err) => {{
        $("cmdReadout").textContent = `发送失败: ${{err.message}}`;
      }});
    }}
    function startHold(linearSign, angularSign, source) {{
      stopHold(false);
      state.active = {{ linearSign, angularSign, source }};
      source?.classList?.add("active");
      drive(linearSign, angularSign);
      state.timer = setInterval(() => drive(linearSign, angularSign), 120);
    }}
    function stopHold(sendStop=true) {{
      if (state.timer) clearInterval(state.timer);
      state.timer = null;
      if (state.active?.source?.classList) state.active.source.classList.remove("active");
      state.active = null;
      $("cmdReadout").textContent = "停止";
      if (sendStop) postJson("/api/stop").catch(() => {{}});
    }}
    function keyVector() {{
      let lin = 0, ang = 0;
      if (state.keys.has("w") || state.keys.has("arrowup")) lin += 1;
      if (state.keys.has("s") || state.keys.has("arrowdown")) lin -= 1;
      if (state.keys.has("a") || state.keys.has("arrowleft")) ang += 1;
      if (state.keys.has("d") || state.keys.has("arrowright")) ang -= 1;
      return {{ lin: Math.max(-1, Math.min(1, lin)), ang: Math.max(-1, Math.min(1, ang)) }};
    }}
    function refreshKeyboardHold() {{
      const v = keyVector();
      if (v.lin || v.ang) startHold(v.lin, v.ang, null);
      else stopHold(true);
    }}
    document.querySelectorAll(".drive-btn").forEach((btn) => {{
      const lin = Number(btn.dataset.lin);
      const ang = Number(btn.dataset.ang);
      btn.addEventListener("pointerdown", (ev) => {{ ev.preventDefault(); btn.setPointerCapture(ev.pointerId); startHold(lin, ang, btn); }});
      btn.addEventListener("pointerup", () => stopHold(true));
      btn.addEventListener("pointercancel", () => stopHold(true));
      btn.addEventListener("pointerleave", () => stopHold(true));
    }});
    $("stopBtn").addEventListener("click", () => stopHold(true));
    $("hardStopBtn").addEventListener("click", () => stopHold(true));
    $("linearSpeed").addEventListener("input", (ev) => {{
      state.linearSpeed = Number(ev.target.value);
      $("linearValue").textContent = state.linearSpeed.toFixed(2);
      if (state.active) drive(state.active.linearSign, state.active.angularSign);
    }});
    $("angularSpeed").addEventListener("input", (ev) => {{
      state.angularSpeed = Number(ev.target.value);
      $("angularValue").textContent = state.angularSpeed.toFixed(2);
      if (state.active) drive(state.active.linearSign, state.active.angularSign);
    }});
    window.addEventListener("keydown", (ev) => {{
      const key = ev.key.toLowerCase();
      if (["w","a","s","d","arrowup","arrowdown","arrowleft","arrowright"].includes(key)) {{
        ev.preventDefault();
        state.keys.add(key);
        refreshKeyboardHold();
      }} else if (key === " " || key === "x") {{
        ev.preventDefault();
        state.keys.clear();
        stopHold(true);
      }}
    }});
    window.addEventListener("keyup", (ev) => {{
      const key = ev.key.toLowerCase();
      if (state.keys.delete(key)) {{
        ev.preventDefault();
        refreshKeyboardHold();
      }}
    }});
    window.addEventListener("blur", () => {{ state.keys.clear(); stopHold(true); }});
    window.addEventListener("pagehide", () => navigator.sendBeacon("/api/stop", new Blob(["{{}}"], {{type: "application/json"}})));
    $("recordBtn").addEventListener("click", async () => {{
      try {{
        if (!state.recording) {{
          await postJson("/api/record/start");
          state.recording = true;
          $("recordBtn").textContent = "停止录制";
        }} else {{
          const data = await postJson("/api/record/stop");
          state.recording = false;
          $("recordBtn").textContent = data.saved ? "已保存" : "开始录制";
          setTimeout(() => $("recordBtn").textContent = "开始录制", 1200);
        }}
      }} catch (err) {{
        $("cmdReadout").textContent = err.message;
      }}
    }});
    $("northBtn").addEventListener("click", async () => {{
      try {{
        const data = await postJson("/api/calibrate/north");
        $("cmdReadout").textContent = `正北校准 ${{data.offset_deg.toFixed(1)}}°`;
      }} catch (err) {{
        $("cmdReadout").textContent = err.message;
      }}
    }});

    function statusClass(el, cls) {{
      el.classList.remove("ok", "warn", "bad");
      if (cls) el.classList.add(cls);
    }}
    function updatePositionHold(payload) {{
      const hold = payload?.vehicle?.position_hold;
      if (!hold) return "实时 RTK";
      if (hold.mode === "moving") return `移动更新 ${{fmtNum(hold.speed_mps, 2)}}m/s`;
      if (hold.mode === "stopped") return `静止锁定 缓存${{fmtNum(hold.cache_age_sec, 1)}}s`;
      if (hold.mode === "init") return "缓存初始化";
      if (hold.mode === "no_odom") return "无里程计 实时RTK";
      if (hold.mode === "odom_stale") return "里程计过期 实时RTK";
      if (hold.mode === "off") return "锁点关闭 实时RTK";
      return hold.mode || "实时 RTK";
    }}
    async function refreshStatus() {{
      try {{
        const res = await fetch("/api/status", {{ cache: "no-store" }});
        const data = await res.json();
        const rb = $("rosbridgePill");
        rb.textContent = data.rosbridge.ok ? `rosbridge :${{data.config.rosbridge_port}}` : `rosbridge 未监听`;
        statusClass(rb, data.rosbridge.ok ? "ok" : "bad");
        const cp = $("controlPill");
        cp.textContent = data.control.active ? "控制中" : "控制待命";
        statusClass(cp, data.control.active ? "warn" : "ok");
        const gp = $("gpsPill");
        gp.textContent = data.gps.lat === null ? "RTK 等待" : `RTK ${{fmtAge(data.gps.age_sec)}}`;
        statusClass(gp, data.gps.lat === null ? "warn" : (data.gps.age_sec <= 2.5 ? "ok" : "warn"));
        const up = $("uePill");
        up.textContent = data.ue_command.raw ? `UE ${{fmtAge(data.ue_command.age_sec)}}` : "UE 等待";
        statusClass(up, data.ue_command.raw ? (data.ue_command.age_sec <= 2 ? "ok" : "warn") : "warn");

        const imu = data.vehicle.imu;
        const odom = data.vehicle.odom;
        const headingSample = imu && Date.now()/1000 - imu.time <= 3 ? imu : odom;
        $("heading").textContent = headingSample ? `${{fmtNum(headingSample.yaw_deg, 1)}}° ENU` : "等待 /imu 或 /odom";
        $("offset").textContent = `${{fmtNum(data.vehicle.heading_offset_deg, 1)}}°`;
        $("speed").textContent = odom?.speed_mps !== null && odom?.speed_mps !== undefined ? `${{fmtNum(odom.speed_mps, 2)}} m/s` : "等待 /odom";
        const yawRate = imu?.angular_velocity?.z ?? odom?.angular_velocity?.z;
        $("yawRate").textContent = yawRate !== null && yawRate !== undefined ? `${{fmtNum(yawRate, 3)}} rad/s` : "--";

        $("fixLat").textContent = data.gps.lat === null ? "--" : fmtNum(data.gps.lat, 8);
        $("fixLon").textContent = data.gps.lon === null ? "--" : fmtNum(data.gps.lon, 8);
        $("fixStatus").textContent = data.gps.status >= 0 ? (data.gps.status === 2 ? "RTK固定" : data.gps.status === 1 ? "差分" : "单点") : "无定位";
        const pos = data.ue_position.payload || {{}};
        $("ueLat").textContent = pos.latitude === undefined ? "--" : fmtNum(pos.latitude, 8);
        $("ueLon").textContent = pos.longitude === undefined ? "--" : fmtNum(pos.longitude, 8);
        $("holdMode").textContent = updatePositionHold(pos);
        $("ueAge").textContent = data.ue_command.raw ? fmtAge(data.ue_command.age_sec) : "等待指令";
        $("ueAge").className = "v " + clsByAge(data.ue_command.age_sec, 2, 30);
        $("ueSummary").textContent = data.ue_command.summary || "等待 UE 指令";
        $("ueRaw").textContent = data.ue_command.raw || "等待 UE 发送消息...";
        state.recording = data.recording.active;
        $("recordBtn").textContent = state.recording ? `停止录制 (${{data.recording.count}})` : "开始录制";

        $("ueTopics").innerHTML = (data.ue_topics || data.topics || []).map((t) => {{
          const toneClass = t.tone === "ok" ? "fresh" : (t.tone === "bad" ? "bad" : "stale");
          return `<div class="topic"><span>${{t.label}}</span><span><span class="${{toneClass}}">${{t.status}}</span><br><span class="mono">${{t.topic}}</span></span><span>pub:${{t.publishers}} sub:${{t.subscribers}}</span></div>`;
        }}).join("");
      }} catch (err) {{
        const cp = $("controlPill");
        cp.textContent = "网页服务断开";
        statusClass(cp, "bad");
      }}
    }}
    async function refreshLog() {{
      try {{
        const name = $("logSelect").value;
        const res = await fetch(`/api/logs?name=${{encodeURIComponent(name)}}&lines=80`, {{ cache: "no-store" }});
        const data = await res.json();
        $("logBox").textContent = data.text || "--";
      }} catch (_err) {{}}
    }}
    $("logSelect").addEventListener("change", refreshLog);
    refreshStatus();
    refreshLog();
    setInterval(refreshStatus, 500);
    setInterval(refreshLog, 2000);
  </script>
</body>
</html>"""


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, app_node: WebControlNode):
        super().__init__(server_address, handler_class)
        self.app_node = app_node


class WebHandler(BaseHTTPRequestHandler):
    server: ThreadedHTTPServer

    def log_message(self, fmt, *args):
        return

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, data) -> None:
        self._send_bytes(status, json_dumps(data), "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_bytes(HTTPStatus.OK, page_html().encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/status":
            self._send_json(HTTPStatus.OK, self.server.app_node.get_status())
            return
        if parsed.path == "/api/logs":
            params = parse_qs(parsed.query)
            name = (params.get("name") or ["ue_bridge"])[0]
            try:
                lines = int((params.get("lines") or ["80"])[0])
            except ValueError:
                lines = 80
            path = LOG_FILES.get(name)
            if path is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown log file"})
                return
            self._send_json(HTTPStatus.OK, {"name": name, "path": str(path), "text": tail_file(path, lines)})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self):
        try:
            body = self._read_json()
            if self.path == "/api/drive":
                linear = body.get("linear", 0.0)
                angular = body.get("angular", 0.0)
                self._send_json(HTTPStatus.OK, self.server.app_node.set_drive(linear, angular))
                return
            if self.path == "/api/stop":
                self._send_json(HTTPStatus.OK, self.server.app_node.stop())
                return
            if self.path == "/api/record/start":
                self._send_json(HTTPStatus.OK, self.server.app_node.start_recording())
                return
            if self.path == "/api/record/stop":
                self._send_json(HTTPStatus.OK, self.server.app_node.stop_recording())
                return
            if self.path == "/api/calibrate/north":
                self._send_json(HTTPStatus.OK, self.server.app_node.calibrate_heading_to_north())
                return
        except (ValueError, TypeError, RuntimeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})


def _spin_safe(node: WebControlNode):
    from rclpy.executors import ExternalShutdownException
    try:
        rclpy.spin(node)
    except (ExternalShutdownException, Exception):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="campusCar web control console")
    parser.add_argument("--host", default=env_str("WEB_GUI_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=WEB_GUI_PORT)
    args = parser.parse_args()

    rclpy.init(args=None)
    node = WebControlNode()
    ros_thread = threading.Thread(target=_spin_safe, args=(node,), daemon=True)
    ros_thread.start()

    server = ThreadedHTTPServer((args.host, args.port), WebHandler, node)
    print(f"[web-gui] 控制台: http://0.0.0.0:{args.port}/", flush=True)
    print(f"[web-gui] MJPEG: http://<NUC_IP>:{MJPEG_PORT}/stream", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.stop()
        finally:
            server.shutdown()
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
