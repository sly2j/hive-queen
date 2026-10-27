---
domain: process
summary: a worker system ships only if a user on another device reaches its sessions without tunnels; Codex deferred, OpenCode v2 only after a spike
affects: [hive/, README.md]
verified: 2026-10-27
source: user 2026-10-27 (supervisor session)
supersedes: .supervisor/archive/memory/decisions/2026-10-27-worker-systems-codex-opencode-plus-proven-remote.md
---
A system ships only if a user on another device can reach its sessions without building tunnels; remote access is the product's point. Codex is deferred until it offers that on Linux. OpenCode v2 is the approved generation and ships only if a spike proves external-device remote access without tunnels. The OpenCode service-password exposure is deferred because the machine is secure.
Why: workers are only useful if reachable remotely; if tunnels are needed, ssh-ing in by hand is easier.
Rejected: shipping Codex or OpenCode as must-haves regardless of remote access; building tunnel management for them.
