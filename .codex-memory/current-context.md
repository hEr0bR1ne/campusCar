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

- Active objective: hardware reuse refactor for deploying the project to two additional cars with different chassis and cameras.
- Current strategy: keep the pushed baseline on `codex/full-stack-ue-rtk-gui`; do refactor work in cloned workspace `_forks/campusCar-hardware-reuse` on branch `codex/hardware-adapter-refactor`.
- Main design: `config/robot.env` is now a common loader; chassis/camera differences live under `config/profiles/*.env`; scripts accept `--profile NAME`.
- Files touched include `config/robot.env`, `config/profiles/`, startup/check/stop/deploy scripts, GUI/UE config loading, docs, and memory files.
- Next recommended step after restart: run shell/Python validation, then commit and push `codex/hardware-adapter-refactor`; after new car hardware details arrive, copy `config/profiles/template.env` into one profile per car and fill chassis/camera fields.

## Update Trigger

- Update this file whenever the user says things like `更新缓存`, `更新记忆`, `记录一下`, or when the current task leaves behind meaningful unfinished state.
