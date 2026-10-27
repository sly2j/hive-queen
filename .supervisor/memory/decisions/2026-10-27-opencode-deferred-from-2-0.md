---
domain: process
summary: OpenCode is deferred from the 2.0 release because its external-device remote gate failed
affects: [hive/]
verified: 2026-10-27
source: user 2026-10-27 (supervisor session)
supersedes:
---
OpenCode does not ship in 2.0; it sits on the roadmap. The `opencode pair --remote` relay did not work from an external device; the user's hypothesis is that their work network blocks it. Revisit when the relay is reachable or OpenCode offers another tunnel-free path.
Why: the tunnel-free remote gate is the ship criterion and it failed.
Rejected: shipping without remote access; building a tunnel around the relay.
