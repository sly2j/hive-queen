---
domain: process
summary: workers: Codex CLI and OpenCode are must-have; ship other systems (pi included) only with a proven remote-access story, rest go to roadmap
affects: [hive/, README.md]
verified: 2026-10-27
source: user 2026-10-27 (supervisor session, AskUserQuestion)
supersedes:
superseded by: .supervisor/memory/decisions/2026-10-27-ship-only-systems-with-tunnel-free-remote.md
---
Codex CLI and OpenCode are required worker systems. Every further system, pi included, ships only if research shows a real remote-access story; the others move to the roadmap.
Why: workers are only useful if the queen can reach them remotely.
Rejected: shipping every system regardless of remote access (unusable workers); Claude plus only the two must-haves (leaves viable systems out).
