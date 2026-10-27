---
domain: process
summary: confirm a third-party CLI's behaviour with a live spike before building on a plan decision about it
affects: [hive/]
verified: 2026-10-27
source: user 2026-10-27
supersedes:
---
A plan decision about how a third-party CLI behaves is confirmed by a live spike before anything is built on it.
Why: two Codex assumptions proved wrong: `-c` hook injection forces embedded mode and detaches from the remote-control daemon, and a non-git queen directory containing `.codex/` still shows the folder-trust prompt.
