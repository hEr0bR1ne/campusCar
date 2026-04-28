# AGENTS.md

## Session Bootstrap

- This repository is the canonical new STM32 chassis workspace at `~/campusCar-new-chassis`; do not route new-chassis work back through `~/campusCar`.
- Before doing substantive work in this repository, read `.codex-memory/project-overview.md` and `.codex-memory/current-context.md`.
- If the current task depends on recent decisions or unfinished work, also read `.codex-memory/session-log.md`.
- If the task concerns chassis hardware, read `.codex-memory/systems/new-chassis.md`; this branch is new direct-UART chassis only.
- Treat `.codex-memory/` as persistent local project memory for this repository.

## Working Rules

- Respond in Chinese unless the user explicitly asks for another language.
- Use `docs/快速启动指南.md`, `docs/UE对接文档.md`, and `docs/部署调试备忘.md` as the canonical checked-in references for startup, UE integration, and debugging details.
- When project context changes materially, or when the user asks to update memory/cache, refresh the relevant files under `.codex-memory/`.
- Do not delete or rewrite `.codex-memory/` wholesale unless the user explicitly asks for it.
