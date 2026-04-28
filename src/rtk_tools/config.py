import os
from pathlib import Path


def _env_float(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.lower() not in ("0", "false", "no", "off")

ROOT_DIR  = Path(__file__).parent.parent.parent  # campusCar/
TOOLS_DIR = ROOT_DIR / "src" / "rtk_tools"
LOG_DIR   = ROOT_DIR / "data" / "logs"
ROS_SETUP = os.environ.get("ROS_SETUP", "/opt/ros/humble/setup.bash")
TS_BRIDGE_SETUP = str(TOOLS_DIR / "rosbridge_ts" / "install" / "setup.bash")

TOPIC_POS_OUT = "/R2UTopic_Pos"
TOPIC_TEXT_OUT = "/R2UTopic_Text"
TOPIC_IMAGE_OUT = "/R2UTopic_Image"
TOPIC_IMAGE_IN = ""  # Optional: source image topic
TOPIC_CMD_IN = "/U2RTopic_Command"
TOPIC_FIX_IN = "/fix"
TOPIC_IMU_IN = os.environ.get("IMU_TOPIC", "/imu")
TOPIC_ODOM_IN = os.environ.get("ODOM_TOPIC", "/odom")

DEFAULT_BAUD = 115200
DEFAULT_BRIDGE_PORT = 9090
DEFAULT_IMAGE_IN = ""

# UE5 位置发送配置
UE_PUBLISH_RATE = _env_float("UE_PUBLISH_RATE", 1.0)  # Hz - UE5 固定 1 秒一次接收位置
UE_INTERPOLATION_ENABLED = _env_bool("UE_INTERPOLATION_ENABLED", True)
RTK_RX_LOG_RATE = _env_float("RTK_RX_LOG_RATE", 0.0)  # Hz; 0 表示不打印不均匀的原始 /fix 接收日志
VEHICLE_HEADING_OFFSET_DEG = _env_float("VEHICLE_HEADING_OFFSET_DEG", 0.0)
RTK_POSITION_HOLD_ENABLED = _env_bool("RTK_POSITION_HOLD_ENABLED", True)
RTK_POSITION_HOLD_SPEED_THRESHOLD_MPS = _env_float("RTK_POSITION_HOLD_SPEED_THRESHOLD_MPS", 0.03)
RTK_POSITION_HOLD_ODOM_TIMEOUT_SEC = _env_float("RTK_POSITION_HOLD_ODOM_TIMEOUT_SEC", 2.0)

SERIAL_GLOBS = [
    "/dev/serial/by-id/*",
    "/dev/ttyACM*",
    "/dev/ttyUSB*",
]
