#!/usr/bin/env bash
# ============================================================
# Start Hikrobot MV-CS016-10GC through camera_aravis2
# ============================================================

set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_ROOT}/config/robot.env"

if [ -f "$ROS_SETUP" ]; then
    set +u
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
    set -u
fi

mkdir -p "$(dirname "$HIKROBOT_ARAVIS_PARAMS_FILE")"

cat > "$HIKROBOT_ARAVIS_PARAMS_FILE" <<EOF
/**:
  ros__parameters:
    guid: "${HIKROBOT_CAMERA_GUID:-}"
    frame_id: "${HIKROBOT_FRAME_ID:-hikrobot_camera}"
    stream_names: []
    verbose: ${HIKROBOT_VERBOSE:-false}
EOF

if [ -n "${HIKROBOT_GEV_PACKET_SIZE:-}" ]; then
    cat >> "$HIKROBOT_ARAVIS_PARAMS_FILE" <<EOF
    TransportLayerControl:
      GevSCPSPacketSize: ${HIKROBOT_GEV_PACKET_SIZE}
EOF
fi

cat >> "$HIKROBOT_ARAVIS_PARAMS_FILE" <<EOF
    ImageFormatControl:
      PixelFormat: "${HIKROBOT_PIXEL_FORMAT:-BGR8}"
      Width: ${HIKROBOT_WIDTH:-1440}
      Height: ${HIKROBOT_HEIGHT:-1080}
    AcquisitionControl:
      ExposureMode: "Timed"
      ExposureAuto: "${HIKROBOT_EXPOSURE_AUTO:-Continuous}"
      AcquisitionFrameRateEnable: true
      AcquisitionFrameRate: ${HIKROBOT_FPS:-30.0}
    AnalogControl:
      GainAuto: "${HIKROBOT_GAIN_AUTO:-Continuous}"
EOF

exec ros2 run camera_aravis2 camera_driver_gv \
    --ros-args \
    -r "__node:=${HIKROBOT_CAMERA_NODE:-hikrobot_camera}" \
    -r "/${HIKROBOT_CAMERA_NODE:-hikrobot_camera}/image_raw:=${IMAGE_TOPIC}" \
    -r "/${HIKROBOT_CAMERA_NODE:-hikrobot_camera}/camera_info:=${CAMERA_INFO_TOPIC}" \
    --params-file "$HIKROBOT_ARAVIS_PARAMS_FILE"
