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

- Active objective: hardware reuse refactor for deploying the project to two additional cars with different chassis and cameras.
- Current strategy: keep the pushed baseline on `codex/full-stack-ue-rtk-gui`; do refactor work in cloned workspace `_forks/campusCar-hardware-reuse` on branch `codex/hardware-adapter-refactor`.
- Main design: `config/robot.env` is now a common loader; chassis/camera differences live under `config/profiles/*.env`; scripts accept `--profile NAME`.
- New chassis direction: upcoming cars connect NUC directly to an STM32 UART chassis rather than NUC -> Orange Pi -> chassis. Exact STM32 serial protocol, device path, and baud confirmation are still missing.
- Seller-provided `_forks/hoverboard-driver-humble.zip` is a ROS2 Humble `ros2_control` hoverboard/differential-drive package using UART frames with start `0xABCD`, `int16 steer`, `int16 speed`, and XOR checksum; it is directly usable only if the STM32 firmware speaks that protocol.
- `_forks/campusCar-hardware-reuse` is intended to be the package installed/flashed onto other cars for future reuse work; treat it as source material for migration, not disposable notes.
- New camera selection: Hikrobot/Hikvision `MV-CS016-10GC`, a 1440x1080 GigE Vision/GenICam industrial camera. Vendor provided no ROS package.
- Hikrobot camera integration is staged through the hardware profile system: `config/profiles/hikrobot_gige.env` skips chassis startup and starts `scripts/hikrobot_camera_start.sh`, which runs `camera_aravis2 camera_driver_gv` and remaps `/hikrobot_camera/image_raw` to the project `IMAGE_TOPIC`.
- `scripts/hikrobot_camera_probe.sh` is the first test entry when the camera arrives; it checks `camera_aravis2`, `arv-tool-0.8`, Aravis enumeration, and ROS2 `camera_finder`.
- Local runtime packages installed on 2026-04-28: `ros-humble-camera-aravis2`, `ros-humble-camera-aravis2-msgs`, `aravis-tools`, `aravis-tools-cli`, and `libaravis-0.8-0`.
- Next recommended step after restart: validate and push `codex/hardware-adapter-refactor`; after new car hardware details arrive, copy `config/profiles/template.env` into one profile per car and fill STM32 UART chassis fields plus camera fields.

## Update Trigger

- Update this file whenever the user says things like `更新缓存`, `更新记忆`, `记录一下`, or when the current task leaves behind meaningful unfinished state.
