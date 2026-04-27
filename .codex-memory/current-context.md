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

- Shutdown checkpoint for 2026-04-27:
  - Current branch is `codex/full-stack-ue-rtk-gui`.
  - Code version was pushed to GitHub; local HEAD and `origin/codex/full-stack-ue-rtk-gui` were aligned at `c46310d Normalize quoted UE command payloads` before this checkpoint edit.
  - The latest working UE integration uses `src/rosbridge_bson_tcp.py` on TCP/BSON port `9090`, not the old rosbridge WebSocket launch.
  - `/U2RTopic_Command` compatibility is in `src/rosbridge_bson_tcp.py`: UE command payloads sent as a BSON dict, as `{data: dict}`, or as an extra-quoted JSON string like `"{"commandId":...}"` are normalized into `std_msgs/String.data`.
  - The successful end-to-end smoke test used a safe `Stop` command and produced `方向指令：Stop  停车` in `data/logs/ue_bridge.log`.
  - Camera startup was optimized to reuse an already publishing Orbbec camera by default and the GUI now prefers local MJPEG frames for faster display.
  - Known hardware note: current Orbbec connection showed `USB2.1` / 480M and cold camera initialization around 40 seconds; USB3 cabling/port is still the likely hardware fix.
  - Next recommended step after reboot: run `cd ~/campusCar && ./scripts/launch_all.sh`, ask UE to resend the standard coordinate command, then watch `data/logs/rosbridge.log`, `data/logs/u2r_command.log`, and `data/logs/ue_bridge.log`.
  - If UE still reaches the bridge but movement does not start, inspect RTK `/fix` and `/heading` readiness rather than JSON transport first.

## Update Trigger

- Update this file whenever the user says things like `更新缓存`, `更新记忆`, `记录一下`, or when the current task leaves behind meaningful unfinished state.
