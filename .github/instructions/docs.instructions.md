---
name: "campusCar docs rules"
description: "Path-specific rules for operator and integration docs under docs/"
applyTo: "docs/**/*.md"
---
# Documentation rules for `docs/`

- Write in Chinese unless the user explicitly asks for another language.
- Optimize for operators and integrators: commands should be copy-pasteable, facts should be concrete, and steps should be short and executable.
- Keep ports, topic names, IP addresses, startup commands, and file paths consistent with the actual scripts and source code.
- Treat `docs/快速启动指南.md`, `docs/UE对接文档.md`, and `docs/部署调试备忘.md` as the canonical operational docs and keep them synchronized when interfaces change.
- For UE streaming guidance, keep HLS as the recommended path and RTSP as a debug path unless the project intentionally changes that policy.
- Preserve high-signal troubleshooting notes such as the correct RTSP port `8554` and other compatibility gotchas when they remain true.
