# Roadmap

Ordered; each item lists what it depends on. All items are planned unless marked deferred.

## R0 Test hive profile
Status: planned. Depends on: none; prerequisite for live validation of everything else.
Decisions: .supervisor/memory/decisions/2026-10-27-hands-on-testing-uses-isolated-test-profile.md
Background: no isolated instance exists. Needed: own config dir, tmux socket, prefix/names and lock; `hive restart` must not touch the fixed systemd unit for a non-default profile. Features can then be exercised live without touching the production hive on this machine or on swarm.

## R1 Driver abstraction for agent systems
Status: planned. Depends on: none; prerequisite for R3, R4, R6.
Decisions: .supervisor/memory/decisions/2026-10-27-ship-only-systems-with-tunnel-free-remote.md
Background: hive is Claude-specific. Needed per system (Claude, OpenCode v2 if its spike proves tunnel-free remote access; Codex is not in this release): launch command, remote-control equivalent, config-dir/trust/permission mechanics, instruction-file and guard equivalents. Likely requires splitting hive/cli.py (1566 lines) so later packages can proceed in parallel.

## R2 Per-instance removal
Status: planned. Depends on: none (independent).
Decisions: none
Background: workers can only be removed by lowering the count. Needed: stop a specific worker (e.g. instance 1 while 2 keeps running); decide hole handling.

## R3 Session done/idle detection
Status: planned. Depends on: R1; research first.
Decisions: none
Background: no signal says a worker finished its turn. Needed: an observable "turn finished / waiting for input" signal per driver (hooks where available, tmux heuristics otherwise) surfaced in `hive list`/`status`, so idle panes can be closed to save tokens.

## R4 Resume sessions
Status: planned. Depends on: R1.
Decisions: none
Background: restarting a worker loses its session. Needed: track session identity per instance and restart a worker resuming its previous session, per driver.

## R5 Multi-node
Status: planned. Depends on: R0 (safe testing on swarm).
Decisions: .supervisor/memory/decisions/2026-10-27-remote-nodes-modeled-hive-side-over-ssh.md, .supervisor/memory/decisions/2026-10-27-dev-builds-on-swarm-use-isolated-venv.md
Background: hive manages one machine. Needed: queen-less `hive` on a remote node; the main queen manages its workers via `hive --node <name> ...` proxied over ssh. Test target: swarm.

## R6 Queen on every supported system
Status: planned. Depends on: R1.
Decisions: .supervisor/memory/decisions/2026-10-27-queen-runs-on-every-supported-system.md
Background: the queen runs only on Claude. Needed: port queen instructions and the PreToolUse-style guard per driver.

## R7 Rename and release
Status: planned. Depends on: all feature items; last.
Decisions: .supervisor/memory/decisions/2026-10-27-rename-repo-and-package-to-hive-queen.md, .supervisor/memory/decisions/2026-10-27-version-scheme-minor-bump-and-release-tags.md, .supervisor/memory/decisions/2026-10-27-landing-policy-squash-merge-and-push.md
Background: repo and package are named `hive`. Needed: repo `hive-queen`, package `hive-queen`, command `hive`, VERSION 2.0, first release tag, upgrade note.

## R8 New-user README and docs/
Status: planned. Depends on: features; can be drafted in parallel.
Decisions: .supervisor/memory/decisions/2026-10-27-docs-short-readme-and-plain-markdown-docs.md
Background: no new-user docs. Needed: short README, docs/ split by topic, getting-started path, per-system guides, multi-node guide.

## R9 Codex driver (when Codex remote control is available on Linux)
Status: deferred. Depends on: R1.
Decisions: .supervisor/memory/decisions/2026-10-27-ship-only-systems-with-tunnel-free-remote.md
Background: Codex is excluded until it offers remote sessions reachable from other devices on Linux.

## R10 pi driver
Status: deferred. Depends on: R1.
Decisions: .supervisor/memory/decisions/2026-10-27-ship-only-systems-with-tunnel-free-remote.md
Background: ships only if it shows a tunnel-free remote-access story.
