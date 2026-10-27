---
domain: process
summary: a worker system ships only if a user on another device reaches its sessions without tunnels, proven by an external-device gate
affects: [hive/, README.md]
verified: 2026-10-27
source: user 2026-10-27 (supervisor session)
supersedes: .supervisor/archive/memory/decisions/2026-10-27-ship-only-systems-with-tunnel-free-remote.md
---
A system ships only if a user on another device can reach its sessions without building tunnels; remote access is the product's point. Each candidate must pass an external-device remote gate before it ships. The OpenCode service-password exposure is deferred because the machine is secure.
Why: workers are only useful if reachable remotely; if tunnels are needed, ssh-ing in by hand is easier.
Rejected: shipping a system as must-have regardless of remote access; building tunnel management for it.
