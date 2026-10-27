---
domain: code
summary: remote nodes are [[nodes]] in config.toml; commands proxied as hive --node NAME over ssh HOST hive, because the queen guard allows only single hive commands
affects: [hive/cli.py, hive/config.example.toml]
verified: 2026-10-27
source: supervisor default 2026-10-27 (user did not object; overturnable)
supersedes:
---
Remote nodes are `[[nodes]]` entries in config.toml; `hive --node <name> ...` runs `ssh <host> hive ...` for the queen.
Why: the queen's guard permits only single `hive` commands, so ssh cannot be issued by the queen directly.
Rejected: letting the queen run ssh itself (breaks the guard).
