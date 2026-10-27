---
domain: process
summary: all hands-on testing uses an isolated test profile and never the production tmux socket, here or on swarm
affects: [hive/]
verified: 2026-10-27
source: supervisor default 2026-10-27 (user did not object; overturnable)
supersedes:
---
Live testing runs only against an isolated test profile (own config dir, tmux socket, names, lock); the production tmux socket is never used, on this machine or on swarm.
Why: tests that spawn, kill or restart workers would otherwise disrupt live production sessions.
