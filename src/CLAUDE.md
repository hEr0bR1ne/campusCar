# CLAUDE.md for `src/`

- Preserve ROS2 topic and message compatibility unless the task explicitly changes an interface.
- Prefer existing config/constants over introducing new hardcoded ports, topics, or robot assumptions.
- Keep runtime-facing logs and operator-facing text in Chinese.
- If a change affects ports, topics, command payloads, or runtime workflow, update the relevant docs in `docs/` and refresh `.codex-memory/`.
