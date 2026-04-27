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
