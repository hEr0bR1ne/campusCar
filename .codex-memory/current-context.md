# Current Context

## Active Environment State

- Codex CLI was upgraded on 2026-04-26.
- Active binary path should be `~/.local/bin/codex`.
- Default Codex model is set to `gpt-5.5`.
- Codex memories are enabled in `~/.codex/config.toml`.
- This repository has a project-local Codex config at `.codex/config.toml`.
- The project-local policy is `approval_policy = "never"` with `sandbox_mode = "danger-full-access"`.
- This repository now also has shared agent instructions for Claude Code and GitHub Copilot.
- Claude Code should load `CLAUDE.md`; VS Code Copilot should load `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md`.
- VS Code Copilot also has path-specific instruction files under `.github/instructions/` for `src/`, `scripts/`, and `docs/`.
- Claude Code also has nested `CLAUDE.md` files under `src/`, `scripts/`, and `docs/` for subtree-specific guidance.

## Persistent Context Strategy

- This repository uses `AGENTS.md` plus `.codex-memory/` as the durable project-memory layer.
- Stable project knowledge belongs in `project-overview.md`.
- Short-term task state and open work should be updated here.
- Recent completed actions and decision trail should be appended to `session-log.md`.

## Current Open Focus

- Field-test restart checkpoint for 2026-04-28:
  - Old chassis work is intentionally isolated in `/home/hkust-gz-nuc/campusCar-old-chassis` on branch `hardware/old-orange-pi-orbbec`.
  - This branch was pushed to `origin/hardware/old-orange-pi-orbbec`; use `git pull --ff-only` after reboot if needed.
  - Desktop entries for the old chassis are `/home/hkust-gz-nuc/桌面/campusCar_Start.desktop` and `/home/hkust-gz-nuc/桌面/campusCar_Control.desktop`; both point to `/home/hkust-gz-nuc/campusCar-old-chassis`.
  - If working from terminal after reboot: `cd ~/campusCar-old-chassis && ./scripts/launch_all.sh`.
  - Quick health check: `cd ~/campusCar-old-chassis && ./scripts/check_all.sh`.
  - Useful logs during field testing: `data/logs/rosbridge.log`, `data/logs/u2r_command.log`, `data/logs/ue_bridge.log`, `data/logs/camera.log`, and `data/logs/mediamtx.log`.
  - This is the Orange Pi / Orbbec old-bottom-board car. Do not switch it to `stm32_hoverboard_4wd`; that profile belongs to `/home/hkust-gz-nuc/campusCar-new-chassis`.

- Current operational workspace for the old Orange Pi/Orbbec chassis is `/home/hkust-gz-nuc/campusCar-old-chassis` on branch `hardware/old-orange-pi-orbbec`; repo desktop launchers and checked docs point here for the old chassis. Do not use the STM32 `stm32_hoverboard_4wd` profile for this car.
- The old-chassis GUI has IMU/odom integration and a compact right-side UE panel: the left nine-button D-pad is intentionally not rendered, and the `UE 最近发送` raw-message box has a vertical scrollbar so long UE JSON messages remain readable.

- Current 4WD movement-control baseline:
  - Pure `a/d`, left/right arrow, GUI button `A/D`, and UE `TurnLeft`/`TurnRight` now pass through `src/motion_profile.py`.
  - After the user reported the X/Z opposite profile caused a very large turning radius, the default was changed back to zero-linear pure angular mode: `(0.0, 0.5)` stays `(0.0, 0.5)`, while combined movement such as `w+a`/`w+d` is still left unchanged as travelling-turn control.
  - Tank-turn related tuning lives in `config/robot.env`: `TANK_TURN_MODE=angular` is the safe default; `experimental_xz` exists only for controlled testing because it makes the current base treat `linear.x` as translation.
  - The remote chassis startup now exports `BASE_TYPE=4WD` through `CAR_BASE_TYPE` before launching `base_control_ros2`, matching the hardware self-report seen in remote logs.

- Pending adaptive refactor discussion:
  - User clarified on 2026-04-28 that the next larger direction is to support two additional robot cars whose chassis and cameras differ from the current campusCar setup.
  - The intended refactor should move the project away from single-car hardcoded assumptions toward selectable per-car profiles for chassis network/startup/control and camera driver/topic/streaming details.
  - New chassis architecture differs from the current car: it is not NUC -> Orange Pi -> chassis; the NUC connects directly to the chassis.
  - New chassis control detail: the direct chassis is STM32-based and controlled from the NUC over UART serial.
  - Seller-provided package found at `_forks/hoverboard-driver-humble.zip`; it is a ROS2 Humble `ros2_control` hoverboard/differential-drive hardware interface, not a camera package.
  - The package sends UART command frames with start `0xABCD`, `int16 steer`, `int16 speed`, and XOR checksum, and expects hoverboard-firmware-style feedback frames. It is only directly usable if the STM32 firmware speaks that protocol or can be changed to match it.
  - Current NUC ROS environment is missing required `ros2_control` packages such as `controller_manager`, `diff_drive_controller`, `joint_state_broadcaster`, and `ros2_control`; deployment must add them before this package can run.
  - `_forks/campusCar-hardware-reuse` is the package intended to be installed/flashed onto other robot cars for future hardware reuse and migration work. Treat it as a key source when preparing other-car deployment, not as disposable reference material.
  - New camera selection: Hikrobot/Hikvision industrial camera `MV-CS016-10GC`.
  - Camera facts researched on 2026-04-28: `MV-CS016-10GC` is a color 1.6 MP GigE area-scan camera, 1440x1080, up to 65.2 fps, Sony IMX296 global shutter, GigE Vision V2.0 and GenICam compatible, powered by 9-24 VDC or PoE. Vendor support said no ROS-specific materials are provided.
  - Recommended ROS2 direction for this camera is to first try `camera_aravis2` on Humble because the camera is GigE Vision/GenICam compatible and `ros-humble-camera-aravis2` is available from apt; fallback is wrapping Hikrobot MVS SDK into a ROS2 image publisher if Aravis cannot configure the device reliably.
  - Hikrobot camera integration has been staged in the project: `CAMERA_MODE=hikrobot_gige_aravis` in `config/robot.env` drives `scripts/launch_all.sh` to start `camera_aravis2 camera_driver_gv`, remap `/hikrobot_camera/image_raw` to the existing `IMAGE_TOPIC=/camera/color/image_raw`, and write generated params to `data/logs/hikrobot_aravis_params.yaml`.
  - `scripts/hikrobot_camera_probe.sh` is the first test entry when the camera arrives; it checks `camera_aravis2`, `arv-tool-0.8`, Aravis enumeration, and ROS2 `camera_finder`.
  - Installed local runtime packages on 2026-04-28: `ros-humble-camera-aravis2`, `ros-humble-camera-aravis2-msgs`, `aravis-tools`, `aravis-tools-cli`, and `libaravis-0.8-0`. `apt-get update` showed a Google Chrome source timeout, but the ROS/Aravis packages installed successfully.
  - Remaining missing details: exact STM32 UART chassis protocol, serial device/baud confirmation, and whether both new cars use the same Hikrobot camera/profile.

- Shutdown checkpoint for 2026-04-27:
  - Current branch is `codex/full-stack-ue-rtk-gui`.
  - Code version was pushed to GitHub; local HEAD and `origin/codex/full-stack-ue-rtk-gui` were aligned at `c46310d Normalize quoted UE command payloads` before this checkpoint edit.
  - The latest working UE integration uses `src/rosbridge_bson_tcp.py` on TCP/BSON port `9090`, not the old rosbridge WebSocket launch.
  - `/U2RTopic_Command` compatibility is in `src/rosbridge_bson_tcp.py`: UE command payloads sent as a BSON dict, as `{data: dict}`, or as an extra-quoted JSON string like `"{"commandId":...}"` are normalized into `std_msgs/String.data`.
  - The successful end-to-end smoke test used a safe `Stop` command and produced `方向指令：Stop  停车` in `data/logs/ue_bridge.log`.
  - Camera startup was optimized to reuse an already publishing Orbbec camera by default and the GUI now prefers local MJPEG frames for faster display.
  - Known hardware note: current Orbbec connection showed `USB2.1` / 480M and cold camera initialization around 40 seconds; USB3 cabling/port is still the likely hardware fix.
  - Next recommended step after reboot: run `cd ~/campusCar-old-chassis && ./scripts/launch_all.sh`, ask UE to resend the standard coordinate command, then watch `data/logs/rosbridge.log`, `data/logs/u2r_command.log`, and `data/logs/ue_bridge.log`.
  - If UE still reaches the bridge but movement does not start, inspect RTK `/fix` and `/heading` readiness rather than JSON transport first.

## Update Trigger

- Update this file whenever the user says things like `更新缓存`, `更新记忆`, `记录一下`, or when the current task leaves behind meaningful unfinished state.
