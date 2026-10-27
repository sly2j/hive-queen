---
domain: code
summary: Codex panes on the shared daemon run their shell commands in the daemon, so pane environment must be set in [shell_environment_policy.set]
affects: [hive/queen.py]
verified: 2026-10-27
source: .supervisor/archive/working/plans/plan-r6-queen-systems.md (Log, unit C spike)
supersedes:
---
A Codex pane attached to the shared remote-control daemon does not pass its own environment to the commands the agent runs; the daemon runs them. Variables the queen's commands need (such as `HIVE_PROFILE`) therefore go into the project `.codex/config.toml` under `[shell_environment_policy.set]`, and are always set because the daemon may have inherited another profile's value.
