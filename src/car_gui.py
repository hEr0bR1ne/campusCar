#!/usr/bin/env python3
"""
小车控制 GUI
功能：键盘控制 / 摄像头图像 / 经纬度显示 / 路径录制
运行：source /opt/ros/humble/setup.bash && python3 car_gui.py
"""
import sys
import os
import threading
import time
import json
import math
from pathlib import Path
from datetime import datetime

# ── ROS2 ──────────────────────────────────────────────────────────────────────
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from sensor_msgs.msg import NavSatFix, Image, CompressedImage
from std_msgs.msg import String

# ── GUI ───────────────────────────────────────────────────────────────────────
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
import cv2
import numpy as np
from PIL import Image as PILImage, ImageTk
from pynput import keyboard as pynput_kb

# ── 配置 ──────────────────────────────────────────────────────────────────────
CAR_IP          = "192.168.100.2"
CMD_VEL_TOPIC   = "/cmd_vel"
FIX_TOPIC       = "/fix"
IMAGE_TOPIC     = "/camera/color/image_flipped"   # 优先尝试
IMAGE_TOPIC_ALT = "/usb_cam/image_raw"
COMPRESSED_TOPIC = IMAGE_TOPIC + "/compressed"

LINEAR_SPEED    = 0.3   # m/s
ANGULAR_SPEED   = 0.5   # rad/s
RECORD_DIR      = Path(__file__).parent.parent / "data" / "recorded_paths"

# ── 颜色主题 ──────────────────────────────────────────────────────────────────
BG       = "#1e1e2e"
BG2      = "#2a2a3e"
ACCENT   = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"
TEXT     = "#cdd6f4"
SUBTEXT  = "#6c7086"

# 字体（在 main() 里 tk.Tk() 之后初始化，避免 rclpy 信号冲突）
FONT_TITLE = FONT_NORMAL = FONT_SMALL = FONT_CARD = FONT_BTN = FONT_MONO = None


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
        self.latest_frame = None   # numpy BGR
        self._lock = threading.Lock()

        # 路径录制
        self.recording = False
        self.path_points = []       # [(lat, lon, alt, timestamp), ...]

        # 订阅 GPS
        self.create_subscription(NavSatFix, FIX_TOPIC, self._on_fix, 10)

        # 订阅图像（尝试多个话题）
        self.create_subscription(Image, IMAGE_TOPIC, self._on_image_raw, 10)
        self.create_subscription(Image, IMAGE_TOPIC_ALT, self._on_image_raw, 10)
        self.create_subscription(CompressedImage, COMPRESSED_TOPIC, self._on_image_compressed, 10)

    # ── 回调 ──────────────────────────────────────────────────────────────────
    def _on_fix(self, msg: NavSatFix):
        with self._lock:
            self.lat = msg.latitude
            self.lon = msg.longitude
            self.alt = msg.altitude
            self.gps_status = msg.status.status
            if self.recording and self.lat is not None:
                self.path_points.append((self.lat, self.lon, self.alt, time.time()))

    def _on_image_raw(self, msg: Image):
        frame = self._decode_raw(msg)
        if frame is not None:
            with self._lock:
                self.latest_frame = frame

    def _on_image_compressed(self, msg: CompressedImage):
        data = np.frombuffer(msg.data, dtype=np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is not None:
            with self._lock:
                self.latest_frame = frame

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
            return self.lat, self.lon, self.alt, self.gps_status

    def get_frame(self):
        with self._lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def get_path_count(self):
        with self._lock:
            return len(self.path_points)


# ══════════════════════════════════════════════════════════════════════════════
# GUI 主窗口
# ══════════════════════════════════════════════════════════════════════════════
class CarGUI:
    def __init__(self, root: tk.Tk, node: CarNode):
        self.root = root
        self.node = node

        # 按键状态
        self._keys_held: set[str] = set()
        self._cmd_timer = None

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

        # ── 顶部标题栏 ────────────────────────────────────────────────────────
        title_bar = tk.Frame(self.root, bg=BG, pady=6)
        title_bar.pack(fill=tk.X, padx=12)
        tk.Label(title_bar, text="小车控制台", font=FONT_TITLE,
                 bg=BG, fg=ACCENT).pack(side=tk.LEFT)
        self.lbl_ros = tk.Label(title_bar, text="ROS2", font=FONT_NORMAL,
                                bg=BG, fg=GREEN)
        self.lbl_ros.pack(side=tk.RIGHT, padx=4)

        # ── 主体：左列 + 右列 ─────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        left = tk.Frame(body, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = tk.Frame(body, bg=BG, width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right.pack_propagate(False)

        # ── 摄像头画面 ────────────────────────────────────────────────────────
        cam_frame = tk.Frame(left, bg=BG2, bd=0, highlightthickness=1,
                             highlightbackground=SUBTEXT)
        cam_frame.pack(fill=tk.BOTH, expand=True)

        self.cam_label = tk.Label(cam_frame, bg="#000000",
                                  text="等待摄像头...", fg=SUBTEXT,
                                  font=FONT_NORMAL)
        self.cam_label.pack(fill=tk.BOTH, expand=True)

        # ── GPS 信息面板 ──────────────────────────────────────────────────────
        gps_panel = self._card(right, "GPS 定位")
        gps_panel.pack(fill=tk.X, pady=(0, 8))

        self.lbl_lat  = self._kv(gps_panel, "纬度")
        self.lbl_lon  = self._kv(gps_panel, "经度")
        self.lbl_alt  = self._kv(gps_panel, "海拔")
        self.lbl_gps_status = self._kv(gps_panel, "状态")

        # ── 键盘控制面板 ──────────────────────────────────────────────────────
        ctrl_panel = self._card(right, "键盘控制")
        ctrl_panel.pack(fill=tk.X, pady=(0, 8))

        self._build_dpad(ctrl_panel)

        speed_row = tk.Frame(ctrl_panel, bg=BG2)
        speed_row.pack(fill=tk.X, pady=(8, 0))
        tk.Label(speed_row, text="线速", bg=BG2, fg=SUBTEXT,
                 font=FONT_SMALL).pack(side=tk.LEFT)
        self.speed_var = tk.DoubleVar(value=LINEAR_SPEED)
        spd_scale = tk.Scale(speed_row, from_=0.05, to=1.0, resolution=0.05,
                 orient=tk.HORIZONTAL, variable=self.speed_var,
                 bg=BG2, fg=TEXT, troughcolor=BG, highlightthickness=0,
                 length=160, takefocus=0)
        spd_scale.pack(side=tk.RIGHT)
        spd_scale.bind("<ButtonRelease-1>", lambda e: self.root.focus_set())

        ang_row = tk.Frame(ctrl_panel, bg=BG2)
        ang_row.pack(fill=tk.X, pady=(2, 0))
        tk.Label(ang_row, text="角速", bg=BG2, fg=SUBTEXT,
                 font=FONT_SMALL).pack(side=tk.LEFT)
        self.ang_var = tk.DoubleVar(value=ANGULAR_SPEED)
        ang_scale = tk.Scale(ang_row, from_=0.1, to=2.0, resolution=0.1,
                 orient=tk.HORIZONTAL, variable=self.ang_var,
                 bg=BG2, fg=TEXT, troughcolor=BG, highlightthickness=0,
                 length=160, takefocus=0)
        ang_scale.pack(side=tk.RIGHT)
        ang_scale.bind("<ButtonRelease-1>", lambda e: self.root.focus_set())

        self.lbl_cmd = tk.Label(ctrl_panel, text="停止", bg=BG2, fg=SUBTEXT,
                                font=FONT_SMALL)
        self.lbl_cmd.pack(anchor=tk.W, pady=(4, 0))

        # ── 录制面板 ──────────────────────────────────────────────────────────
        rec_panel = self._card(right, "路径录制")
        rec_panel.pack(fill=tk.X, pady=(0, 8))

        self.btn_record = tk.Button(
            rec_panel, text="开始录制", font=FONT_BTN,
            bg=GREEN, fg=BG, activebackground="#7ec87a", relief=tk.FLAT,
            padx=12, pady=6, cursor="hand2", command=self._toggle_record)
        self.btn_record.pack(fill=tk.X)

        self.lbl_rec_info = tk.Label(rec_panel, text="未录制", bg=BG2,
                                     fg=SUBTEXT, font=FONT_SMALL)
        self.lbl_rec_info.pack(anchor=tk.W, pady=(4, 0))

        # ── 底部状态栏 ────────────────────────────────────────────────────────
        status_bar = tk.Frame(self.root, bg=BG2, pady=4)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.lbl_status = tk.Label(status_bar, text="就绪  |  WASD/方向键控制  |  空格停止",
                                   bg=BG2, fg=SUBTEXT, font=FONT_SMALL)
        self.lbl_status.pack(side=tk.LEFT, padx=10)

    def _card(self, parent, title: str) -> tk.Frame:
        """带标题的卡片容器"""
        outer = tk.Frame(parent, bg=BG)
        tk.Label(outer, text=title, bg=BG, fg=ACCENT,
                 font=FONT_CARD).pack(anchor=tk.W, pady=(0, 4))
        inner = tk.Frame(outer, bg=BG2, padx=10, pady=8,
                         highlightthickness=1, highlightbackground=SUBTEXT)
        inner.pack(fill=tk.X)
        return inner

    def _kv(self, parent, label: str) -> tk.Label:
        """键值行，返回值标签"""
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill=tk.X, pady=1)
        tk.Label(row, text=label, bg=BG2, fg=SUBTEXT,
                 font=FONT_SMALL, width=5, anchor=tk.W).pack(side=tk.LEFT)
        val = tk.Label(row, text="--", bg=BG2, fg=TEXT,
                       font=FONT_MONO, anchor=tk.W)
        val.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return val

    def _build_dpad(self, parent):
        """方向键示意图"""
        dpad = tk.Frame(parent, bg=BG2)
        dpad.pack(pady=(4, 0))

        btn_cfg = dict(width=3, height=1, relief=tk.FLAT, font=FONT_NORMAL,
                       bg=BG, fg=TEXT, activebackground=ACCENT, cursor="hand2")

        self.btn_fwd  = tk.Button(dpad, text="^", **btn_cfg,
                                  command=lambda: self._manual_cmd(1, 0))
        self.btn_back = tk.Button(dpad, text="v", **btn_cfg,
                                  command=lambda: self._manual_cmd(-1, 0))
        self.btn_left = tk.Button(dpad, text="<", **btn_cfg,
                                  command=lambda: self._manual_cmd(0.3, 1))
        self.btn_right= tk.Button(dpad, text=">", **btn_cfg,
                                  command=lambda: self._manual_cmd(0.3, -1))
        self.btn_stop = tk.Button(dpad, text="[]", width=3, height=1,
                                  relief=tk.FLAT, font=FONT_NORMAL,
                                  bg=RED, fg=BG, activebackground="#e07090",
                                  cursor="hand2", command=self._stop_car)

        self.btn_fwd.grid (row=0, column=1, padx=2, pady=2)
        self.btn_left.grid(row=1, column=0, padx=2, pady=2)
        self.btn_stop.grid(row=1, column=1, padx=2, pady=2)
        self.btn_right.grid(row=1,column=2, padx=2, pady=2)
        self.btn_back.grid(row=2, column=1, padx=2, pady=2)

    # ── 键盘绑定（pynput 全局监听，不依赖 tkinter 焦点）────────────────────────
    def _bind_keys(self):
        CONTROL_KEYS = {
            pynput_kb.KeyCode.from_char('w'), pynput_kb.KeyCode.from_char('a'),
            pynput_kb.KeyCode.from_char('s'), pynput_kb.KeyCode.from_char('d'),
            pynput_kb.Key.up, pynput_kb.Key.down,
            pynput_kb.Key.left, pynput_kb.Key.right,
            pynput_kb.Key.space,
        }

        def on_press(key):
            try:
                if hasattr(key, 'char') and key.char:
                    k = key.char.lower()
                else:
                    k = key.name if hasattr(key, 'name') else str(key)
                if k == 'space':
                    self._keys_held.clear()
                else:
                    self._keys_held.add(k)
            except Exception:
                pass

        def on_release(key):
            try:
                if hasattr(key, 'char') and key.char:
                    k = key.char.lower()
                else:
                    k = key.name if hasattr(key, 'name') else str(key)
                self._keys_held.discard(k)
                if not self._keys_held:
                    self.node.stop()
            except Exception:
                pass

        self._kb_listener = pynput_kb.Listener(on_press=on_press, on_release=on_release)
        self._kb_listener.start()
        # 持续发送指令的定时器（50ms = 20Hz）
        self._cmd_loop()

    def _cmd_loop(self):
        if self._keys_held:
            self._apply_keys()
        self.root.after(50, self._cmd_loop)

    def _apply_keys(self):
        lin = ang = 0.0
        spd = self.speed_var.get()
        asp = self.ang_var.get()
        if "w" in self._keys_held or "up" in self._keys_held:
            lin += spd
        if "s" in self._keys_held or "down" in self._keys_held:
            lin -= spd
        if "a" in self._keys_held or "left" in self._keys_held:
            ang += asp
        if "d" in self._keys_held or "right" in self._keys_held:
            ang -= asp
        # 阿克曼：转向时给最小线速度
        if ang != 0.0 and lin == 0.0:
            lin = spd * 0.5
        self.node.send_cmd(lin, ang)
        dirs = []
        if lin > 0: dirs.append("前进")
        elif lin < 0: dirs.append("后退")
        if ang > 0: dirs.append("左转")
        elif ang < 0: dirs.append("右转")
        self.lbl_cmd.config(text=" + ".join(dirs) if dirs else "停止",
                            fg=YELLOW if dirs else SUBTEXT)

    def _manual_cmd(self, lin_sign: float, ang_sign: float):
        spd = self.speed_var.get()
        asp = self.ang_var.get()
        self.node.send_cmd(lin_sign * spd, ang_sign * asp)
        self.root.after(400, self._stop_car)

    def _stop_car(self):
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
        self._update_camera()
        if self._recording:
            cnt = self.node.get_path_count()
            self.lbl_rec_info.config(text=f"录制中... {cnt} 个点")

    def _update_gps(self):
        lat, lon, alt, status = self.node.get_gps()
        if lat is None:
            self.lbl_lat.config(text="--", fg=SUBTEXT)
            self.lbl_lon.config(text="--", fg=SUBTEXT)
            self.lbl_alt.config(text="--", fg=SUBTEXT)
            self.lbl_gps_status.config(text="无信号", fg=RED)
        else:
            self.lbl_lat.config(text=f"{lat:.7f}°", fg=TEXT)
            self.lbl_lon.config(text=f"{lon:.7f}°", fg=TEXT)
            self.lbl_alt.config(text=f"{alt:.2f} m", fg=TEXT)
            if status >= 0:
                label = "RTK固定" if status == 2 else ("差分" if status == 1 else "单点")
                self.lbl_gps_status.config(text=f"● {label}", fg=GREEN)
            else:
                self.lbl_gps_status.config(text="● 无定位", fg=RED)

    def _update_camera(self):
        frame = self.node.get_frame()
        if frame is None:
            return
        # 用父容器尺寸而非 Label 自身，避免正反馈撑大
        w = self.cam_label.master.winfo_width()
        h = self.cam_label.master.winfo_height()
        if w < 10 or h < 10:
            w, h = 640, 360
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
    root.geometry("1000x640")

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
        node.stop()
        if hasattr(app, '_kb_listener'):
            app._kb_listener.stop()
        root.destroy()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_close()


if __name__ == "__main__":
    main()

