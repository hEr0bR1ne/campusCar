# Project Overview

## Project

- Name: `campusCar-new-chassis`
- Purpose: NUC-side control and integration workspace for the new STM32 direct-UART robot chassis, covering vehicle control, Hikrobot camera streaming, RTK/GPS, and UE5 command bridging.

## Main Entry Points

- Full stack start: `./scripts/launch_all.sh`
- Full stack stop: `./scripts/stop_all.sh`
- Health check: `./scripts/check_all.sh`
- Keyboard control: `./scripts/keyboard_control.sh`
- Dependency deployment: `./scripts/deploy_dependencies.sh`
- Docker image build: `./scripts/docker_build.sh`
- Docker STM32 chassis shell/run: `./scripts/docker_run_stm32.sh`
- STM32 hoverboard chassis probe: `./scripts/stm32_hoverboard_probe.sh`
- STM32 hoverboard chassis start: `./scripts/stm32_hoverboard_start.sh`

## Key Configuration

- Common config loader: `config/robot.env`
- Hardware profiles: `config/profiles/*.env`
- Default new-chassis profile: `config/profiles/stm32_hoverboard_4wd.env`
- Local secret overrides: `config/profiles/*.local.env` and `config/robot.local.env` (ignored by Git)
- Important fields:
  - `ROBOT_PROFILE`: selected hardware profile, default `stm32_hoverboard_4wd`
  - `SUDO_PASS`: local NUC sudo password
  - `CHASSIS_START_MODE`: `local_command` or `skip`
  - `CHASSIS_DEPENDENCY_MODE`: `hoverboard_ros2_control`
  - `HOVERBOARD_FRONT_DEVICE` / `HOVERBOARD_REAR_DEVICE`: STM32 driver serial devices
  - `CAMERA_START_MODE`: `command` or `skip`
  - `CAMERA_DEPENDENCY_MODE`: `hikrobot_aravis`, `custom`, or `none`

## Main Components

- `src/car_gui.py`: control GUI
- `src/keyboard_control.py`: direct keyboard control
- `src/rtsp_server.py`: RTSP video pipeline
- `src/mjpeg_server.py`: MJPEG preview service
- `src/ue_bridge.py`: UE command bridge
- `hardware/hoverboard_driver`: ROS2 control driver for STM32 dual-UART hoverboard-style 4WD chassis
- `src/rtk_tools/path_recorder.py`: GPS path recording
- `src/rtk_tools/gps_navigator.py`: waypoint navigation
- `src/rtk_tools/u2r_r2u_bridge.py`: ROS bridge between UE-facing topics and robot topics

## System-Specific Memory

- New/direct STM32 chassis details live in `.codex-memory/systems/new-chassis.md`.
- This workspace lives at `~/campusCar-new-chassis` and no longer supports the old Orange-Pi/Orbbec chassis path; keep common project architecture here and keep STM32 wiring/vendor protocol facts in the system file.

## Runtime Network Facts

- NUC IP: `192.168.100.1`
- New STM32 chassis uses local dual UART, not a chassis IP/SSH hop.

## Service Ports

- `8554/tcp`: RTSP via `mediamtx`
- `8888/tcp`: HLS via `mediamtx`
- `8080/tcp`: MJPEG HTTP preview
- `9090/tcp`: rosbridge TCP / WebSocket integration point

## ROS2 Topics

- `/U2RTopic_Command`: UE command input
- `/R2UTopic_Pos`: RTK position JSON sent toward UE, now with an added `vehicle` object for IMU/odom state
- `/R2UTopic_Text`: text/status reply sent toward UE
- `/cmd_vel`: robot motion control
- `/fix`: GPS position
- `/odom`: chassis odometry / estimated speed
- `/imu`: optional vehicle IMU/feedback topic; UE should tolerate missing vehicle fields.
- `/heading`: heading quaternion currently expected by UE/navigation bridge (`geometry_msgs/msg/QuaternionStamped`)

## UE Integration Facts

- Recommended UE video input: HLS `http://192.168.100.1:8888/robot_cam/index.m3u8`
- Debug RTSP input: `rtsp://192.168.100.1:8554/robot_cam`
- Correct RTSP port is `8554`, not `8854`
- UE control uses rosbridge on `ws://192.168.100.1:9090`
- UE commands are wrapped as `std_msgs/String` JSON payloads published to `/U2RTopic_Command`

## Operational Notes

- `launch_all.sh` is the normal startup path and handles cleanup, local STM32 serial checks, chassis startup, camera, RTK, streaming, UE bridge, and GUI startup.
- `launch_all.sh`, `check_all.sh`, `stop_all.sh`, `deploy_dependencies.sh`, `keyboard_control.sh`, and `open_car_gui.sh` accept `--profile NAME`.
- Chassis and camera differences should be introduced through `config/profiles/<profile>.env` before changing shared scripts.
- RTK serial absence should not block the rest of the stack; startup is designed to skip RTK-specific steps when unavailable.
- Logs are documented under `data/logs/` with per-service log files such as `camera.log`, `rosbridge.log`, `ue_bridge.log`, and `mediamtx.log`.
- Docker isolation uses one ROS2 Humble runtime image, `campuscar:humble`; `docker_run_stm32.sh` fixes `ROBOT_PROFILE=stm32_hoverboard_4wd`.
- If Docker Hub direct pulls fail, build the image with `--base-image docker.m.daocloud.io/library/ros:humble-ros-base-jammy`.

## Canonical Docs

- `docs/快速启动指南.md`
- `docs/UE对接文档.md`
- `docs/部署调试备忘.md`
- `docs/硬件复用指南.md`
- `docs/Docker部署指南.md`
