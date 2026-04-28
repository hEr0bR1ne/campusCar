# Project Overview

## Project

- Name: `campusCar`
- Purpose: NUC-side control and integration workspace for a campus robot car, covering vehicle control, camera streaming, RTK/GPS, and UE5 command bridging.

## Main Entry Points

- Full stack start: `./scripts/launch_all.sh`
- Full stack stop: `./scripts/stop_all.sh`
- Health check: `./scripts/check_all.sh`
- Web control console: `./scripts/open_web_gui.sh`
- Boot autostart setup/status: `./scripts/install_autostart_service.sh`
- Keyboard control: `./scripts/keyboard_control.sh`
- Dependency deployment: `./scripts/deploy_dependencies.sh`

## Key Configuration

- Primary config file: `config/robot.env`
- Important fields:
  - `CAR_IP`: robot chassis IP, currently documented as `192.168.100.2`
  - `CAR_USER` / `CAR_PASS`: chassis SSH login
  - `SUDO_PASS`: local NUC sudo password
  - `CAR_LAUNCH_CMD`: remote ROS2 launch command for the chassis

## Main Components

- `src/car_gui.py`: control GUI
- `src/car_web_gui.py`: browser-based control console on `8088`
- `src/keyboard_control.py`: direct keyboard control
- `src/rtsp_server.py`: RTSP video pipeline
- `src/mjpeg_server.py`: MJPEG preview service
- `src/ue_bridge.py`: UE command bridge
- `src/rtk_tools/path_recorder.py`: GPS path recording
- `src/rtk_tools/gps_navigator.py`: waypoint navigation
- `src/rtk_tools/u2r_r2u_bridge.py`: ROS bridge between UE-facing topics and robot topics

## Runtime Network Facts

- NUC IP: `192.168.100.1`
- Robot chassis IP: `192.168.100.2`

## Service Ports

- `8554/tcp`: RTSP via `mediamtx`
- `8888/tcp`: HLS via `mediamtx`
- `8080/tcp`: MJPEG HTTP preview
- `8088/tcp`: browser control console
- `9090/tcp`: rosbridge TCP / WebSocket integration point

## ROS2 Topics

- `/U2RTopic_Command`: UE command input
- `/R2UTopic_Pos`: GPS position JSON sent toward UE
- `/R2UTopic_Text`: text/status reply sent toward UE
- `/cmd_vel`: robot motion control
- `/fix`: GPS position
- `/heading`: orientation

## UE Integration Facts

- Recommended UE video input: HLS `http://192.168.100.1:8888/robot_cam/index.m3u8`
- Debug RTSP input: `rtsp://192.168.100.1:8554/robot_cam`
- Correct RTSP port is `8554`, not `8854`
- UE control uses rosbridge on `ws://192.168.100.1:9090`
- UE commands are wrapped as `std_msgs/String` JSON payloads published to `/U2RTopic_Command`

## Operational Notes

- `launch_all.sh` is the normal startup path and handles cleanup, connectivity checks, remote chassis startup, camera, RTK, streaming, UE bridge, and GUI startup.
- Full-stack startup defaults to the browser console (`src/car_web_gui.py`) and does not pop the Tk GUI unless `START_CONTROL_GUI=1`.
- Boot autostart is a user systemd unit named `campuscar-old-chassis.service`; it starts `LIVE_RTK_LOGS=0 START_WEB_GUI=1 START_CONTROL_GUI=0 ./scripts/launch_all.sh`.
- RTK serial absence should not block the rest of the stack; startup is designed to skip RTK-specific steps when unavailable.
- Logs are documented under `data/logs/` with per-service log files such as `camera.log`, `rosbridge.log`, `ue_bridge.log`, and `mediamtx.log`.

## Canonical Docs

- `docs/快速启动指南.md`
- `docs/UE对接文档.md`
- `docs/部署调试备忘.md`
