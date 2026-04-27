# campusCar repository instructions for GitHub Copilot

- Respond in Chinese unless the user explicitly asks for another language.
- Before making substantive changes, load the shared project memory files:
  - [Project Overview](../.codex-memory/project-overview.md)
  - [Current Context](../.codex-memory/current-context.md)
  - [Session Log](../.codex-memory/session-log.md)
- Use `docs/快速启动指南.md`, `docs/UE对接文档.md`, and `docs/部署调试备忘.md` as the canonical references for startup, UE integration, and debugging details.
- Prefer the repository scripts for normal operations:
  - `./scripts/launch_all.sh`
  - `./scripts/stop_all.sh`
  - `./scripts/check_all.sh`
  - `./scripts/keyboard_control.sh`
- Treat `.codex-memory/` as the durable project-memory layer for this repository. When the user asks to update memory/cache, refresh the relevant files there.
