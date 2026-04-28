# Session Log

## 2026-04-26

- Upgraded Codex CLI to the newer user-local installation under `~/.local/bin/codex`.
- Removed the older system-wide `/usr/bin/codex` installation.
- Set the default Codex model to `gpt-5.5`.
- Planned repository-level persistence via `AGENTS.md` and `.codex-memory/`.
- Created `.codex-memory/` with project overview, current context, and session-log files to avoid re-explaining project background after restart.
- Renamed the repo-root empty `.codex` placeholder file to `.codex.empty.backup`.
- Added project-local `.codex/config.toml` with `approval_policy = "never"` and `sandbox_mode = "danger-full-access"`.
- Added root `CLAUDE.md` so Claude Code can reuse the same project memory files across sessions.
- Added `.github/copilot-instructions.md` and `.vscode/settings.json` so VS Code Copilot can load shared repo instructions and default new chat sessions to autopilot mode.
- Set `.claude/settings.local.json` to `defaultMode = "bypassPermissions"` for low-friction local Claude Code sessions on this machine.
- Added path-specific Copilot instruction files under `.github/instructions/` for `src/**/*.py`, `scripts/**/*.sh`, and `docs/**/*.md`.
- Added nested `CLAUDE.md` files under `src/`, `scripts/`, and `docs/` so Claude Code gets subtree-specific guidance while reusing the shared project memory model.

## 2026-04-27

- Updated `scripts/launch_all.sh` so the RTK full stack startup visibly includes RTK driver, rosbridge TCP, and RTK/UE bridge output in the launch terminal while still writing logs under `data/logs/`.
- Added `LIVE_RTK_LOGS=0` as the quiet-start toggle for suppressing live RTK/rosbridge terminal output.
- Documented the live RTK/rosbridge output behavior in `docs/快速启动指南.md` and `docs/部署调试备忘.md`.
- Added timestamps to the live RTK/rosbridge terminal output.
- Fixed `campusCar_Start.desktop` to use the absolute project path and installed it to `/home/hkust-gz-nuc/桌面/campusCar_Start.desktop`.
- Changed the RTK/UE bridge so `/R2UTopic_Pos` is emitted by a fixed-rate timer at `UE_PUBLISH_RATE=1.0` by default; terminal `[R2U TX]` lines now represent actual UE coordinate sends, while irregular raw `/fix` RX logging is disabled by default with `RTK_RX_LOG_RATE=0`.
- Restored `/R2UTopic_Pos` JSON payload schema to the original UE contract: `status`, `status_name`, `latitude`, `longitude`, `altitude`, `timestamp`, `frame_id` only.
- Formatted `/R2UTopic_Pos` `latitude` and `longitude` as JSON numbers with exactly 8 decimal places while preserving the fixed UE JSON field contract.
- Integrated keyboard driving into the startup `car_gui.py` console using Tk key bindings.
- Reworked the GUI keyboard driving behavior to follow the official `teleop_twist_keyboard` layout from `/home/hkust-gz-nuc/old/rosCar`: `u/i/o`, `j/k/l`, `m/,/.` for motion and `q/z`, `w/x`, `e/c` for speed scaling.
- Updated the GUI keyboard layer back to WASD/game-style input while preserving the official Twist control logic: hold `w/a/s/d` or arrow keys to move, use combined keys for diagonal movement, release to stop, and use `r/f`, `t/g`, `q/z` for speed scaling.
- Changed the GUI motion buttons to the same hold-to-run behavior as the keyboard: button press starts motion and button release or pointer leave stops.
- Optimized camera/full-stack startup: `launch_all.sh` now reuses an already publishing Orbbec camera by default, skips USB reset unless `RESET_ORBBEC_USB=1`, opens the GUI earlier, and avoids restarting the ROS daemon unless `REFRESH_ROS_DAEMON=1`.
- Added GUI MJPEG-first camera display via `CAR_GUI_CAMERA_SOURCE=auto` and `MJPEG_STREAM_URL`, so the control console can show an existing local MJPEG stream immediately while keeping ROS image subscriptions as fallback.
- Changed camera consumers and launch-time camera probes to ROS2 sensor-data QoS, reducing false image-topic timeouts during camera discovery.
- Confirmed current Orbbec connection is `USB2.1` at 480M and `camera.log` showed roughly 40 seconds of device initialization; USB3 cabling/port remains the hardware-side fix for cold-start latency.
- Added `/U2RTopic_Command` compatibility in `src/rosbridge_bson_tcp.py`: if UE publishes the business command JSON as a BSON dict instead of a `std_msgs/String.data` string, the adapter converts it into the string payload before handing it to rosbridge.
- Extended the same adapter to fix UE payloads that arrive as an extra quoted JSON object string like `"{"commandId":...}"`; the wrapper quotes are stripped before publishing to `/U2RTopic_Command`.
- Pushed current baseline commit `c46310d` to GitHub branch `codex/full-stack-ue-rtk-gui`.
- Created remote refactor branch `codex/hardware-adapter-refactor` and cloned it locally at `_forks/campusCar-hardware-reuse` for hardware reuse work.
- Started hardware profile refactor: moved chassis/camera-specific settings into `config/profiles/campus_car.env`, added `config/profiles/template.env`, kept local secrets in ignored `*.local.env`, and added `--profile` support to startup/check/stop/deploy/control scripts.

## 2026-04-28

- User clarified that the adaptive refactor target is two additional cars with different chassis and cameras, not the 2026-04-27 UE/RTK startup robustness work.
- Current known direction: use a multi-car profile mechanism so chassis network/start/control assumptions and camera launch/topic/streaming assumptions are not hardcoded for only the current car.
- User clarified that the new chassis path is direct NUC-to-chassis, not NUC-to-Orange-Pi-to-chassis, and that the direct chassis is STM32-based UART control.
- Inspected seller package `_forks/hoverboard-driver-humble.zip`: it is a ROS2 Humble `hoverboard_driver` package using `ros2_control`, `diff_drive_controller`, and a UART hoverboard protocol (`0xABCD` command frame with steer/speed/checksum). It does not contain camera support or STM32 firmware.
- Verified the current NUC ROS environment does not have the required `ros2_control` runtime packages installed (`controller_manager`, `diff_drive_controller`, `joint_state_broadcaster`, and `ros2_control` missing).
- User clarified that `_forks/campusCar-hardware-reuse` is the package that should eventually be installed/flashed onto other robot cars for hardware reuse/migration.
- User selected Hikrobot/Hikvision industrial camera `MV-CS016-10GC`; vendor/customer service provided no ROS materials.
- Researched camera route: `MV-CS016-10GC` is a color GigE Vision/GenICam camera. For ROS2 Humble, prefer `camera_aravis2` first; use Hikrobot MVS SDK wrapper only if Aravis fails.
- Added staged Hikrobot GigE camera support on the hardware refactor branch: `config/profiles/hikrobot_gige.env`, `scripts/hikrobot_camera_start.sh`, `scripts/hikrobot_camera_probe.sh`, common `HIKROBOT_*` env vars, Aravis dependency checks, and docs.
- Installed local Hikrobot/Aravis runtime packages (`ros-humble-camera-aravis2`, `ros-humble-camera-aravis2-msgs`, `aravis-tools`, `aravis-tools-cli`, `libaravis-0.8-0`). Probe script passes dependency checks and reports no camera connected.
- Added shared `src/motion_profile.py` so pure yaw commands are reshaped for the current 4WD base: `a/d`, left/right arrows, GUI `A/D`, terminal keyboard control, and UE `TurnLeft`/`TurnRight` keep `angular.z` but add opposite-signed `linear.x` assist for four-wheel pivot behavior.
- Added `PIVOT_TURN_LINEAR_SCALE`, `PIVOT_TURN_MIN_LINEAR`, and `PIVOT_TURN_MAX_LINEAR` to `config/robot.env`; default `0.5 rad/s` pure left turn reshapes from `(0.0, 0.5)` to `(-0.15, 0.5)`, while travelling turns such as `(0.3, 0.5)` are unchanged.
- Added `CAR_BASE_TYPE=4WD` and changed `CAR_LAUNCH_CMD` to export `BASE_TYPE=${CAR_BASE_TYPE}` before launching `base_control_ros2`, because remote logs showed the chassis self-reporting `Type:4WD` while non-interactive SSH startup missed `.bashrc`'s `BASE_TYPE`.
- User clarified that the desired behavior is a true tank turn: left-side and right-side wheels should have opposite speeds. Replaced the earlier compensation profile with equal-magnitude opposite-side encoding: default pure left turn now reshapes from `(0.0, 0.5)` to `(-0.5, 0.5)`, while travelling turns remain unchanged.
- Renamed the pivot tuning knobs to `TANK_TURN_SIDE_SPEED_SCALE`, `TANK_TURN_MIN_SIDE_SPEED`, and `TANK_TURN_MAX_SIDE_SPEED`; legacy `PIVOT_TURN_*` names are still read as fallbacks by `src/motion_profile.py`.
- User reported the equal-opposite X/Z profile produced an excessive turning radius, which means the current base firmware still interprets `linear.x` as translational velocity rather than a left/right side-speed slot. Changed the safe default to `TANK_TURN_MODE=angular`, so pure `a/d` again publishes `(0.0, angular)` with no injected linear component.
- Kept `experimental_xz` mode in `src/motion_profile.py` for controlled future tests only; true tank-turn behavior likely needs a lower-level driver/firmware path that exposes left/right wheel speed instead of trying to encode it through standard `/cmd_vel`.
- Merged `origin/main` into `codex/hardware-adapter-refactor`; resolved conflicts by keeping the hardware profile design and preserving main's movement-control and shutdown checkpoint context.
- Inspected seller chassis reply in `_forks/驱动器控制答疑回复(1).docx`: it confirms the hoverboard-driver serial protocol matches the STM32/driver, uses 115200 8N1 5V TTL over RX/TX/GND, requires two serial ports for front and rear motor drivers, treats speed/steer as RPM-oriented values, and currently has no encoder data from the actual driver.
- Integrated the new STM32 dual-UART chassis path into `codex/hardware-adapter-refactor`: imported `hardware/hoverboard_driver`, added `stm32_hoverboard_4wd` profile, start/probe scripts, ros2_control dependency deployment, and compact no-encoder feedback support.
- Researched the current old-car bottom-board 9-axis IMU path: remote `base_control_ros2` publishes `/imu` as `sensor_msgs/msg/Imu` at about 50 Hz by querying serial command `0x13` and parsing response `0x14` into gyro, accel, and quaternion fields. Live NUC DDS checks confirmed `/imu` data is readable; `/heading` is a separate `nmea_navsat_driver` `QuaternionStamped` topic and should not be assumed to be the chassis IMU.
- Split chassis memory into `.codex-memory/systems/old-chassis.md` and `.codex-memory/systems/new-chassis.md`; moved old chassis IMU details into the old-chassis system file and kept `current-context.md` as a pointer plus current focus only.
- Added chassis state integration: GUI now subscribes to `/imu` and `/odom` to show compass heading, speed, yaw rate, acceleration, and freshness; RTK/UE bridge now appends a `vehicle` object to `/R2UTopic_Pos` so UE receives RTK position and vehicle state together.
- Checked wheel-speed/encoder feasibility: old chassis exposes chassis-level `/odom` but no per-wheel encoder topic; new STM32 hoverboard path can use compact feedback `speedR_meas/speedL_meas` as wheel speed, but true encoder tick feedback requires full frames with `wheelR_cnt/wheelL_cnt`, which the seller says the current actual driver lacks.
- Continued seller-reply integration for the new STM32 chassis: added `HOVERBOARD_COMMAND_LIMIT_RPM=50` through the profile/start script/driver, clamped serial `steer/speed` commands against the seller `[-1000,1000]` range, sent zero command on driver shutdown, remapped hoverboard controller odom to `/odom`, and expanded probe/docs/memory with the no-timeout/no-encoder safety notes.
- Added Docker environment isolation: `docker/Dockerfile.humble`, `docker/entrypoint.sh`, old/new chassis compose files, `docker_build.sh`, `docker_run_old.sh`, `docker_run_stm32.sh`, and `docs/Docker部署指南.md`. Old chassis container fixes `ROBOT_PROFILE=campus_car`; new STM32 container fixes `ROBOT_PROFILE=stm32_hoverboard_4wd`.
- Added `scripts/install_docker.sh` and sudo-aware Docker wrappers (`CAMPUSCAR_DOCKER_SUDO=1`) for installing Docker and building/running the image. Attempted installation on 2026-04-28 but it stopped at sudo password input; current session has no `SUDO_PASS` and no TTY password path.
- Configured the local sudo override in ignored `config/robot.local.env` and intentionally did not store the raw sudo secret in `.codex-memory/`.
- Installed Docker on the NUC through `scripts/install_docker.sh`: `docker.io`, Docker Buildx, Docker Compose v2, `containerd`, and the `docker` group are present; the Docker daemon is active.
- Built `campuscar:humble` successfully. Direct `ros:humble-ros-base-jammy` pulls from Docker Hub failed, so the successful build used `docker.m.daocloud.io/library/ros:humble-ros-base-jammy` through `scripts/docker_build.sh --base-image`.
- Verified old chassis Docker entry with `sg docker -c './scripts/docker_run_old.sh --no-gui --no-devices -- ./scripts/check_all.sh --profile campus_car'`; the script ran inside the container and reported current host stack state, with old chassis IP and Orbbec driver not reachable/running in this hardware-less check.
- Fixed `scripts/deploy_dependencies.sh` so the hoverboard colcon build runs from `hoverboard_ws/` instead of using unsupported `colcon build --log-base`.
- Fixed `hardware/hoverboard_driver/hardware/include/hoverboard_driver/pid.hpp` by adding the missing `rclcpp/rclcpp.hpp` include required for `rclcpp::Node`, logging macros, and `rclcpp::Clock`.
- Rebuilt `hoverboard_driver` inside the new STM32 Docker entry with `--rebuild-hoverboard`; `ros2 pkg prefix hoverboard_driver` now resolves under `hoverboard_ws/install`.
- Verified new STM32 Docker entry with `scripts/stm32_hoverboard_probe.sh`; ROS2 dependencies and `hoverboard_driver` pass, while `/dev/ttyUSB0` and `/dev/ttyUSB1` are still absent because the test ran without chassis serial devices.
- Converted `codex/hardware-adapter-refactor` into a new-chassis-only branch: removed `config/profiles/campus_car.env`, the old chassis Docker wrapper/compose, the camera-only Hikrobot test profile, and `.codex-memory/systems/old-chassis.md`.
- Changed `config/robot.env` default `ROBOT_PROFILE` to `stm32_hoverboard_4wd`, removed old chassis IP/SSH defaults, and made `launch_all.sh` preflight the STM32 hoverboard setup plus front/rear serial devices before starting the full stack.
- Simplified `scripts/deploy_dependencies.sh` to the new STM32/Hikrobot dependency path, removing Orbbec source/udev/build options from this branch.
- Updated `docs/快速启动指南.md`, `docs/Docker部署指南.md`, `docs/硬件复用指南.md`, and `docs/部署调试备忘.md` so the checked-in docs no longer instruct users to run the old chassis path.
- Diagnosed the desktop launcher failure: the `.desktop` files were executable/trusted and `gnome-terminal` existed, but the launch command still used the old direct host path while the current branch expects STM32 Docker runtime; additionally the current login session had not refreshed docker-group membership even though `hkust-gz-nuc` is in the `docker` group.
- Added `scripts/desktop_run_stm32.sh` and updated `/home/hkust-gz-nuc/桌面/campusCar_Start.desktop` plus `/home/hkust-gz-nuc/桌面/campusCar_Control.desktop` to launch the STM32 Docker full stack/GUI explicitly, using `sg docker` automatically until logout/relogin refreshes Docker permissions.
- Investigated the new STM32 launch failure `新底盘串口不存在：/dev/ttyUSB0`: host had AirM2M `/dev/ttyACM0..3` and one CH340 USB serial adapter visible in `lsusb` but unbound to `ch341`. Manually binding `1-3.2:1.0` created `/dev/ttyUSB0`; probe now passes the front serial path and still correctly fails on missing rear `/dev/ttyUSB1`.
- Added `scripts/bind_ch341_serial.sh`, wired it into desktop launch/probe/full-stack preflight, and created ignored `config/profiles/stm32_hoverboard_4wd.local.env` mapping the current CH340 front link to `/dev/serial/by-path/pci-0000:00:14.0-usb-0:3.2:1.0-port0`.
- Moved the canonical new-chassis workspace out of the old `~/campusCar` tree to `~/campusCar-new-chassis`, including `.codex-memory/`, `AGENTS.md`, `CLAUDE.md`, `.github/` Copilot instructions, `.codex/config.toml`, the seller ROS package zip, and the seller answer document.
- Moved the ignored `hoverboard_ws/` colcon workspace to `~/campusCar-new-chassis/hoverboard_ws` so the new root project keeps the built `hoverboard_driver` package and the old `~/campusCar` project no longer holds this new-chassis build output.
- Rebuilt `hoverboard_ws/` inside the STM32 Docker runtime from the new root path; `stm32_hoverboard_probe.sh` now resolves `hoverboard_driver` under `/workspace/campusCar-new-chassis/hoverboard_ws/install/hoverboard_driver`.
- Renamed the new-chassis branch to `hardware/new-stm32-hikrobot`; repo desktop launchers now point at `/home/hkust-gz-nuc/campusCar-new-chassis` and use the STM32 Docker launcher/check/stop path instead of legacy `~/campusCar` commands.
