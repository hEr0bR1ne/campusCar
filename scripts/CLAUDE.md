# CLAUDE.md for `scripts/`

- Keep scripts automation-friendly and non-interactive by default.
- Reuse the existing project bootstrap pattern: derive `PROJECT_ROOT`, source `config/robot.env`, and use the established environment variables.
- Prefer idempotent cleanup and startup behavior so repeated runs do not fail on stale processes or occupied ports.
- When script behavior changes, update the matching docs and project memory files.
