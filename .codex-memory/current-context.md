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
  - New chassis work is intentionally isolated in `/home/hkust-gz-nuc/campusCar-new-chassis` on branch `hardware/new-stm32-hikrobot`.
  - This branch was pushed to `origin/hardware/new-stm32-hikrobot`; use `git pull --ff-only` after reboot if needed.
  - Desktop entries for the new chassis are `/home/hkust-gz-nuc/桌面/新底盘_全栈.desktop` and `/home/hkust-gz-nuc/桌面/新底盘_控制台.desktop`; both call `scripts/desktop_run_stm32.sh`.
  - If working from terminal after reboot: `cd ~/campusCar-new-chassis && ./scripts/stm32_hoverboard_probe.sh` first, then `./scripts/hikrobot_camera_probe.sh`, then `./scripts/desktop_run_stm32.sh fullstack` when hardware checks pass.
  - Docker is installed and `campuscar:humble` exists locally. If the login session still lacks direct Docker group permissions, the desktop wrapper should fall back to `sg docker`; a logout/login also refreshes the group membership.
  - Current known serial state: front CH340 link is mapped through ignored `config/profiles/stm32_hoverboard_4wd.local.env` to `/dev/serial/by-path/pci-0000:00:14.0-usb-0:3.2:1.0-port0`; rear `/dev/ttyUSB1` still needs the second USB-TTL/driver link to be connected or identified.
  - Safety default remains `HOVERBOARD_COMMAND_LIMIT_RPM=50`. Do not raise this during first outside tests until serial direction, sign convention, and stopping behavior are confirmed.

- Active branch for the new STM32/Hikrobot chassis work is `hardware/new-stm32-hikrobot` in the independent `~/campusCar-new-chassis` workspace.
- This workspace was moved out of `~/campusCar/_forks` on 2026-04-28 so new-chassis work and seller materials no longer live under the old chassis project directory.
- `origin/main` has been merged into this branch on 2026-04-28; conflict resolution kept the profile-based hardware adapter design and absorbed the useful main-branch checkpoint/context.
- Main design: this branch is new STM32 chassis only. `config/robot.env` defaults to `stm32_hoverboard_4wd`; startup/check/stop/deploy/control scripts may still accept `--profile NAME`, but `campus_car` is no longer present or supported.
- Docker isolation is through `docker/Dockerfile.humble`, `scripts/docker_build.sh`, and `scripts/docker_run_stm32.sh`; old chassis Docker entrypoints were removed.

- Chassis memory now lives in `.codex-memory/systems/new-chassis.md`; the old chassis memory file was removed from this branch to prevent accidental reintroduction.

- Current new-chassis focus:
  - Continue new-bottom-board work through the `stm32_hoverboard_4wd` profile and `template.env`, not through the old `campus_car` profile.
  - The new direct chassis is STM32 UART based and should use the seller-confirmed `0xABCD` steer/speed/checksum protocol with two serial ports for front/rear drivers.
  - STM32 hoverboard-style chassis integration is staged in `config/profiles/stm32_hoverboard_4wd.env`, `hardware/hoverboard_driver`, `scripts/stm32_hoverboard_start.sh`, and `scripts/stm32_hoverboard_probe.sh`.
  - Seller reply confirms `steer/speed` command range `[-1000,1000]`; the staged profile/driver now defaults to `HOVERBOARD_COMMAND_LIMIT_RPM=50` for arrival-day safety.
  - The integrated hoverboard driver can use compact feedback `speedR_meas/speedL_meas` as wheel velocity feedback, but current seller feedback has no encoder tick counts; full encoder position feedback needs firmware/full feedback frames with `wheelR_cnt/wheelL_cnt`.
  - Remaining validation: exact serial device naming, sign convention, safe RPM limits under load, and whether both new cars share the same Hikrobot camera settings.

- Current Docker focus:
  - Docker is the preferred main environment isolation path for ROS2/apt dependencies; Conda should remain for offline Python tools only.
  - Docker is installed on the NUC, the daemon is active, and the user `hkust-gz-nuc` is in the `docker` group. Existing shells may still need `newgrp docker` or relogin; `sg docker -c '...'` works immediately.
  - The local Docker image `campuscar:humble` was built successfully on 2026-04-28. Direct Docker Hub pulls failed, so the successful build used base image `docker.m.daocloud.io/library/ros:humble-ros-base-jammy`.
  - The Docker image includes ROS2 Humble, rosbridge, RTK/video dependencies, Aravis/Hikrobot packages, `ros2_control`, `diff_drive_controller`, `controller_manager`, Cyclone DDS support, and mediamtx.
  - Runtime still uses host network and host hardware devices because ROS2 DDS, video ports, USB/TTL, RTK, and GigE Vision require host integration.
  - Use `./scripts/docker_run_stm32.sh` for the STM32/Hikrobot profile.
  - Desktop launchers now call `scripts/desktop_run_stm32.sh`, which uses the STM32 Docker entry and falls back to `sg docker` when the current login session has not refreshed docker-group membership.
  - `scripts/bind_ch341_serial.sh` auto-binds unbound CH340 USB serial adapters before STM32 launch/probe, because the first detected CH340 initially appeared in `lsusb` without creating `/dev/ttyUSB0`.
  - Docker install helper is `./scripts/install_docker.sh`; local sudo automation can be configured through ignored `config/robot.local.env`. Do not copy raw sudo secrets into `.codex-memory/`.
  - `hoverboard_driver` was rebuilt successfully inside the new STM32 container after fixing its missing `rclcpp` include and making `deploy_dependencies.sh` use `hoverboard_ws/` as the colcon workspace. After moving this project to `~/campusCar-new-chassis`, `hoverboard_ws/` was rebuilt there so its colcon paths no longer reference the old workspace.
  - Software-level new STM32 container probe passes for ROS2 dependencies and `hoverboard_driver`; `/dev/ttyUSB0` and `/dev/ttyUSB1` still show missing when running with `--no-devices` or without the chassis connected.
  - Current physical serial state after CH340 binding: front is mapped locally to `/dev/serial/by-path/pci-0000:00:14.0-usb-0:3.2:1.0-port0`; rear `/dev/ttyUSB1` is still missing until the second USB-TTL/front-rear driver link is connected or identified.

- Current branch checkpoint:
  - Active branch is `hardware/new-stm32-hikrobot`, now treated as the new chassis branch.
  - Old chassis runtime files were removed: `config/profiles/campus_car.env`, `scripts/docker_run_old.sh`, `docker/compose.old_chassis.yml`, and `.codex-memory/systems/old-chassis.md`.
  - Seller-provided new-chassis package, answer document, and `hoverboard_ws/` build workspace now live under `~/campusCar-new-chassis/`, not under `~/campusCar`.
  - `src/rosbridge_bson_tcp.py` remains the UE TCP/BSON compatibility point on port `9090`.
  - Next hardware step after reboot: run `cd ~/campusCar-new-chassis && ./scripts/stm32_hoverboard_probe.sh`, confirm the two serial devices, then run `./scripts/hikrobot_camera_probe.sh` and only then start through the STM32 Docker path or the fixed desktop launcher.

## Update Trigger

- Update this file whenever the user says things like `更新缓存`, `更新记忆`, `记录一下`, or when the current task leaves behind meaningful unfinished state.
