---
domain: code
summary: Codex remote-control pairing survives a daemon restart; only `codex remote-control start` is needed, and the daemon has no autostart
affects: [hive/]
verified: 2026-10-27
source: user 2026-10-27 (supervisor session)
supersedes:
---
After the Codex remote-control daemon restarts, the existing pairing with the Codex app still holds; only `codex remote-control start` is needed, with no re-pairing. The daemon does not autostart, so hive must ensure it is running at launch. Unverified: whether a second `start` on a running daemon errors.
