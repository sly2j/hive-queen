---
domain: code
summary: Codex 0.164.0 project hooks in .codex/hooks.json keep the shared daemon; -c overrides and hook-trust bypass force embedded mode
affects: [hive/]
verified: 2026-10-27
source: user 2026-10-27 (supervisor session)
supersedes:
---
Codex 0.164.0 loads project hooks from `<dir>/.codex/hooks.json` without forcing embedded mode, so the pane stays on the shared remote-control daemon. `-c` overrides and `--dangerously-bypass-hook-trust` force embedded mode. Hook trust is stored only in the user's ~/.codex/config.toml and is re-requested when the hook hash changes. A non-git directory containing `.codex/` shows Codex's folder-trust prompt.
