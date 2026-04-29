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

- **2026-04-29 收尾存档 — 明早调试入口**：
  - 今天完成了 `src/ue_bridge.py` 运动控制双闭环改造，代码已提交并推送到 `hardware/old-orange-pi-orbbec`。
  - 明早调试入口：`docs/速度闭环调试指南.md`，按步骤操作即可。
  - 关键操作：先 `kill <ue_bridge PID>`，再前台 `python3 src/ue_bridge.py`，看到 `速度闭环：kp=0.8 ki=0.3` 说明新代码已加载。
  - 调参入口：`config/robot.env` 里的 `UE_SPEED_KP`、`UE_SPEED_KI`、`UE_NAV_MIN_SPEED`、`UE_NAV_DECEL_DIST`，改完重启 `ue_bridge.py` 即生效。
  - 速度环日志关键词：`[速度环]`（方向控制）、`[导航速度环]`（坐标导航）；没有这两行说明在走开环（`/odom` 缺失或超时，属正常退化）。

- **ue_bridge.py 双闭环改造内容（2026-04-29）**：
  - 新增 `/odom` 订阅，提取 `hypot(vx, vy)` 作为速度反馈，受 `_lock` 保护。
  - 新增 `SpeedPI` 类：带积分限幅（`MAX_LINEAR_SPEED / ki`）的 PI 控制器，防止启动瞬间积分爆炸。
  - 方向控制：解析可选 `duration` 字段，实际超时 = `min(duration, DIRECTION_TIMEOUT_SEC)`；前进/后退走速度闭环，纯转向跳过闭环。
  - 坐标导航：外环线性减速曲线（`dist < NAV_DECEL_DIST` 时从目标速度降到 `NAV_MIN_SPEED`）+ 内环速度 PI；转向对准阶段重置积分。
  - `/odom` 超时时两处均退化为开环并重置积分，fail-open 设计。
  - 每 10 个控制周期打印一行调参日志，不影响正常运行。
  - 新增 5 个 `config/robot.env` 配置项：`UE_SPEED_KP=0.8`、`UE_SPEED_KI=0.3`、`UE_SPEED_ODOM_TIMEOUT=1.0`、`UE_NAV_MIN_SPEED=0.08`、`UE_NAV_DECEL_DIST=1.5`。

- **收尾流程定义（用户约定）**：
  - 用户说"收尾"时，执行以下三步：
    1. 写调试/操作文档到 `docs/` 目录（供明天继续工作用）
    2. 更新 `.codex-memory/`（`current-context.md` 写当前状态和下一步，`session-log.md` 追加今日工作记录）；`.codex-memory/` 是所有 AI agent 共享的持久记忆层
    3. `git add` 相关文件，`git commit`，`git push` 到 GitHub

- Field-test restart checkpoint for 2026-04-29:
  - Old chassis work is intentionally isolated in `/home/hkust-gz-nuc/campusCar-old-chassis` on branch `hardware/old-orange-pi-orbbec`.
  - If working from terminal after reboot: `cd ~/campusCar-old-chassis && ./scripts/launch_all.sh`.
  - Full-stack startup defaults to the browser console at `http://<NUC_IP>:8088/` via `src/car_web_gui.py`.
  - Boot autostart is managed by the user systemd unit `campuscar-old-chassis.service`; check with `systemctl --user status campuscar-old-chassis.service --no-pager`.
  - Quick health check: `cd ~/campusCar-old-chassis && ./scripts/check_all.sh`.
  - Useful logs: `data/logs/ue_bridge.log`, `data/logs/web_gui.log`, `data/logs/rosbridge.log`, `data/logs/u2r_command.log`, `data/logs/camera.log`.
  - This is the Orange Pi / Orbbec old-bottom-board car. Do not switch it to `stm32_hoverboard_4wd`.

- Current operational workspace for the old Orange Pi/Orbbec chassis is `/home/hkust-gz-nuc/campusCar-old-chassis` on branch `hardware/old-orange-pi-orbbec`.
- The old-chassis GUI has IMU/odom integration and a compact right-side UE panel.
- `src/car_gui.py` has a `设为正北` button; `src/rtk_tools/core/bridge.py` watches config file mtime for heading offset reload.
- RTK position hold is enabled by default (`RTK_POSITION_HOLD_ENABLED=1`); GUI shows `坐标源` state.
- `TANK_TURN_MODE=angular` is the safe default for 4WD turning.

- Pending adaptive refactor (not started):
  - Two new cars with STM32 direct-UART chassis and Hikrobot MV-CS016-10GC GigE camera.
  - `camera_aravis2` is the preferred ROS2 route for the Hikrobot camera.
  - `_forks/campusCar-hardware-reuse` is the key package for other-car deployment.
  - Missing: exact STM32 UART protocol, serial device/baud, whether both new cars share the same camera profile.
  - Old chassis work is intentionally isolated in `/home/hkust-gz-nuc/campusCar-old-chassis` on branch `hardware/old-orange-pi-orbbec`.
  - The 2026-04-29 save point should include the browser console/autostart work and the UE-link status simplification; check `git log -1 --oneline` after reboot for the latest commit.
  - Desktop entries for the old chassis are `/home/hkust-gz-nuc/桌面/campusCar_Start.desktop`, `/home/hkust-gz-nuc/桌面/campusCar_Control.desktop`, and `/home/hkust-gz-nuc/桌面/campusCar_Web.desktop`; all point to `/home/hkust-gz-nuc/campusCar-old-chassis` or the local web console.
  - If working from terminal after reboot: `cd ~/campusCar-old-chassis && ./scripts/launch_all.sh`.
  - Full-stack startup now defaults to the browser console at `http://<NUC_IP>:8088/` via `src/car_web_gui.py`; the current observed NUC URL on 2026-04-29 is `http://10.12.171.184:8088/`, but this IP may change with Wi-Fi/network.
  - The old Tk GUI remains available with `START_CONTROL_GUI=1 ./scripts/launch_all.sh` or `./scripts/open_car_gui.sh`.
  - Both the browser console and Tk GUI show explicit UE link status rows for `/U2RTopic_Command`, `/R2UTopic_Pos`, and `/R2UTopic_Text` instead of generic ROS topic lists.
  - Boot autostart is managed by the user systemd unit `campuscar-old-chassis.service`, installed/enabled by `./scripts/install_autostart_service.sh`; it starts `LIVE_RTK_LOGS=0 START_WEB_GUI=1 START_CONTROL_GUI=0 ./scripts/launch_all.sh`.
  - Check autostart after reboot with `systemctl --user status campuscar-old-chassis.service --no-pager`; disable only if needed with `./scripts/install_autostart_service.sh --disable`.
  - Quick health check: `cd ~/campusCar-old-chassis && ./scripts/check_all.sh`.
  - Useful logs during field testing: `data/logs/web_gui.log`, `data/logs/rosbridge.log`, `data/logs/u2r_command.log`, `data/logs/ue_bridge.log`, `data/logs/camera.log`, and `data/logs/mediamtx.log`.
  - This is the Orange Pi / Orbbec old-bottom-board car. Do not switch it to `stm32_hoverboard_4wd`; that profile belongs to `/home/hkust-gz-nuc/campusCar-new-chassis`.

- Current operational workspace for the old Orange Pi/Orbbec chassis is `/home/hkust-gz-nuc/campusCar-old-chassis` on branch `hardware/old-orange-pi-orbbec`; repo desktop launchers and checked docs point here for the old chassis. Do not use the STM32 `stm32_hoverboard_4wd` profile for this car.
- The old-chassis GUI has IMU/odom integration and a compact right-side UE panel: the left nine-button D-pad is intentionally not rendered, and the `UE 最近发送` raw-message box has a vertical scrollbar so long UE JSON messages remain readable.
- On 2026-04-28 during field testing, the vehicle was physically pointing roughly west while `/imu` raw ENU yaw read about `123.1°`. `config/robot.env` initially sets `VEHICLE_HEADING_OFFSET_DEG=56.9`, so GUI and `/R2UTopic_Pos.vehicle` yaw calibrate that posture to about `180.0° ENU` (west). This is a rough field offset, not a full magnetometer calibration.
- `src/car_gui.py` now has a bottom-state `设为正北` button. Put the car's nose toward true north, click the button, and it computes `VEHICLE_HEADING_OFFSET_DEG = 90° - raw_yaw`, writes it back to `config/robot.env`, and updates the GUI immediately. `src/rtk_tools/core/bridge.py` watches the same config file so `/R2UTopic_Pos.vehicle` can pick up the new heading offset while running.
- To reduce UE-side apparent RTK drift while stopped, `src/rtk_tools/core/bridge.py` now has position hold enabled by default. `/R2UTopic_Pos` still publishes at `UE_PUBLISH_RATE`, but its coordinate source is a single overwritten cache: if fresh `/odom` speed is greater than `RTK_POSITION_HOLD_SPEED_THRESHOLD_MPS=0.03`, the cache updates from RTK; if speed is at or below the threshold, UE receives the cached coordinate. If `/odom` is missing/stale for more than `RTK_POSITION_HOLD_ODOM_TIMEOUT_SEC=2.0`, it falls back to live RTK instead of holding an old point indefinitely.
- The GUI now shows the RTK position-hold state in the `/R2UTopic_Pos 发给 UE` block as `坐标源`: `移动更新`, `静止锁定`, `无里程计 实时RTK`, or `里程计过期 实时RTK`. This state comes from `vehicle.position_hold` in the outgoing JSON.

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

## Update Trigger

- Update this file whenever the user says things like `更新缓存`, `更新记忆`, `记录一下`, or when the current task leaves behind meaningful unfinished state.
