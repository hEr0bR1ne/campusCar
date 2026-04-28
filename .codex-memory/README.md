# campusCar Codex Memory

This folder is the persistent project memory layer for Codex sessions in this repository.

Canonical workspace: `~/campusCar-new-chassis`. New STM32 chassis work and seller materials should stay here, not under the old `~/campusCar` project.

Files:

- `project-overview.md`: stable project background, architecture, interfaces, and operational facts.
- `current-context.md`: what is currently important, active assumptions, and near-term focus.
- `session-log.md`: short chronological notes for recent work that may matter after a restart.
- `systems/new-chassis.md`: stable memory for the new direct-UART STM32 chassis system.

Usage:

- `AGENTS.md` instructs Codex to read these files at the start of each new session in this repo.
- Keep stable facts in `project-overview.md`.
- Keep chassis-specific facts in `systems/new-chassis.md` instead of mixing them into `current-context.md`.
- Keep volatile or task-specific status in `current-context.md`.
- Append short entries to `session-log.md` after meaningful work or when the user asks to update memory.
