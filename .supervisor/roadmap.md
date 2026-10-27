# Roadmap

Ordered; each item lists what it depends on. All items are deferred.

## R9 OpenCode driver and queen (deferred: external-device relay failed the remote gate; retry off the work network)
Status: deferred. Depends on: none.
Decisions: .supervisor/memory/decisions/2026-10-27-opencode-deferred-from-2-0.md, .supervisor/memory/decisions/2026-10-27-ship-only-systems-with-tunnel-free-remote-2.md
Background: OpenCode does not ship until `opencode pair --remote` or another tunnel-free path reaches sessions from an external device.

## R10 pi driver
Status: deferred. Depends on: none.
Decisions: .supervisor/memory/decisions/2026-10-27-ship-only-systems-with-tunnel-free-remote-2.md
Background: ships only if it shows a tunnel-free remote-access story.

## R11 Codex rules-based prompts
Status: deferred. Depends on: none.
Decisions: .supervisor/memory/decisions/2026-10-27-codex-ships-as-worker-and-queen.md
Background: the Codex queen answers every case the Claude queen asks about with a deny and a run-by-hand message. Needed: `-a on-request` plus `.codex/rules` replacing that deny-with-message.

## R12 Codex worker hooks via a daemon-loaded config layer
Status: deferred. Depends on: none.
Decisions: .supervisor/memory/decisions/2026-10-27-ship-only-systems-with-tunnel-free-remote-2.md
Background: Codex workers run without hive's status hooks because `-c` and hook-trust bypass force embedded mode, so done detection falls back to tmux heuristics and no session id is captured. Needed: hooks from a config layer the shared daemon loads (project `.codex` hooks or `[hooks]` in config.toml), giving done detection and session capture without leaving the daemon.

## R13 Codex session lookup for resume
Status: deferred. Depends on: none.
Decisions: none
Background: `hive stop --keep-session` is refused for Codex and resume is manual (`codex resume`). Needed: look the session up from ~/.codex/state_5.sqlite (or hooks, R12) so `spawn --resume` works for Codex.

## R14 PyPI publication
Status: deferred. Depends on: none.
Decisions: none
Background: `hive-queen` installs from the git URL only. Needed: publish the package to PyPI.

## R15 Single list-panes call for `hive list`
Status: deferred. Depends on: none.
Decisions: none
Background: `hive list` makes an extra tmux call to read pane state. Needed: carry the fields in `RunningPane` so one list-panes call serves it.

## R16 Guard check for `spawn --system` abbreviations
Status: deferred. Depends on: none.
Decisions: none
Background: the queen guard asks for `hive spawn --system X` unless X is already configured. Needed: check how it handles abbreviated forms of `--system` and close any gap.
