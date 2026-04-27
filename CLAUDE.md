# CLAUDE.md

This repository uses shared project memory files. Load them before substantive work:

@.codex-memory/project-overview.md
@.codex-memory/current-context.md
@.codex-memory/session-log.md

## Working Rules

- Respond in Chinese unless the user explicitly asks for another language.
- Use `docs/快速启动指南.md`, `docs/UE对接文档.md`, and `docs/部署调试备忘.md` as the canonical checked-in references for startup, UE integration, and debugging details.
- When the user asks to update memory/cache, or when project state changes materially, refresh the relevant files under `.codex-memory/`.
- Treat `.codex-memory/` as the durable project-memory layer for this repository.
