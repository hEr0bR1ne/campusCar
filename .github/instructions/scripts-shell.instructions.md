---
name: "campusCar script rules"
description: "Path-specific rules for automation scripts under scripts/"
applyTo: "scripts/**/*.sh"
---
# Script rules for `scripts/`

- Follow the existing Bash style in this repo: derive `PROJECT_ROOT`, source `config/robot.env`, and rely on existing environment variables before adding new ones.
- Prefer idempotent startup and cleanup logic. Process termination, port cleanup, and service checks should tolerate repeated runs.
- Keep scripts non-interactive by default. Avoid adding new blocking prompts such as `read -p` in normal automation paths unless the user explicitly asks for them.
- Send long-running service output to `data/logs/` with stable, per-service log filenames.
- Reuse existing helper patterns such as `need_cmd`, timestamped logging helpers, and guarded cleanup with `|| true` when they fit the surrounding file.
- If a script changes startup order, service ports, log locations, required dependencies, or operator workflow, update the matching docs in `docs/` and refresh `.codex-memory/`.
