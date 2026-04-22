from pathlib import Path

ROOT_DIR  = Path(__file__).parent.parent.parent  # campusCar/
TOOLS_DIR = ROOT_DIR / "src" / "rtk_tools"
LOG_DIR   = ROOT_DIR / "data" / "logs"
ROS_SETUP = "/opt/ros/humble/setup.bash"
TS_BRIDGE_SETUP = str(TOOLS_DIR / "rosbridge_ts" / "install" / "setup.bash")

TOPIC_POS_OUT = "/R2UTopic_Pos"
TOPIC_TEXT_OUT = "/R2UTopic_Text"
TOPIC_IMAGE_OUT = "/R2UTopic_Image"
TOPIC_IMAGE_IN = ""  # Optional: source image topic
TOPIC_CMD_IN = "/U2RTopic_Command"
TOPIC_FIX_IN = "/fix"

DEFAULT_BAUD = 115200
DEFAULT_BRIDGE_PORT = 9090
DEFAULT_IMAGE_IN = ""

# 小车连接信息（与 start_all.sh 保持一致）
CAR_IP   = "192.168.100.2"
CAR_USER = "bingda"
CAR_PASS = "bingda"

# UE5 位置发送配置
UE_PUBLISH_RATE = 1.0  # Hz - UE5 接收位置数据的频率（推荐 10-30Hz）
UE_INTERPOLATION_ENABLED = True  # 是否启用线性插值平滑

SERIAL_GLOBS = [
    "/dev/serial/by-id/*",
    "/dev/ttyACM*",
    "/dev/ttyUSB*",
]
