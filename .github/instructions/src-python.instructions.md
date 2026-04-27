---
name: "campusCar source rules"
description: "Path-specific rules for ROS2 and Python source files under src/"
applyTo: "src/**/*.py"
---
# Source rules for `src/`

- Keep ROS2 topic names, message types, and UE command JSON compatibility stable unless the task explicitly requires an interface change.
- Reuse existing constants, config modules, and `config/robot.env` values instead of scattering ports, topic names, or device assumptions across files.
- Prefer small, local changes that preserve the current runtime topology: chassis control, camera streaming, RTK/GPS, and UE bridging.
- Keep dependencies minimal. Prefer Python stdlib and the existing ROS2 stack unless the change clearly needs a new dependency.
- Keep user-facing logs and operator-facing messages in Chinese when they are printed to terminals or GUIs.
- If a source change alters ports, topics, command payloads, startup order, or operational workflow, update the relevant docs in `docs/` and refresh `.codex-memory/project-overview.md` or `.codex-memory/current-context.md`.
