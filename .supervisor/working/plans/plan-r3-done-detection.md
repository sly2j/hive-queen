# Plan: R3 done/idle detection

Child plan of `.supervisor/working/plans/plan-hive-queen-2.0.md`, package R3, release `2.x`.
Planned 2026-10-27 against `main` b5136c0 (R0, R1a, R2, R5 landed) and the R1 branch
`feat/r1-claude-driver` at 8ed901d (Slices 1, 2, 4 of `plan-r1-drivers.md`; the driver
interface cited below is that child plan's, assumptions listed in `## Assumptions`). Binding:
D10, D16 as amended 2026-10-27 (OpenCode poll, Codex hooks via `-c`, `notify` rejected), D17
(R4 reads `session_id` from the status file), the SAFETY CONTRACT. Research:
`.supervisor/working/research/2026-10-27-hive-queen-2.0-systems.md` ("research, A3" and "B").

## Goal

Every running pane shows a state the user and the queen can act on: `busy`, `done` (finished
its turn, waiting for input), `blocked` (waiting for a permission or question), `dead` (agent
gone, shell back), or the tmux-only `quiet`. Primary source: the agent's own lifecycle events,
delivered by a hive hook script to `<profile dir>/state/status/<name>.json`; fallback: a tmux
screen-stability heuristic that never claims `done`. `hive list` and `hive status` print
`state=<v> source=hook|api|tmux age=<s>` per pane. R4 reads `session_id` from the same file.

Non-goals: stopping idle workers (a later queen instruction, not code here); an SSE/event
watcher process (one-shot polling only); resume commands (R4); queen rewrites beyond the one
`hive list` bullet; a state database (D10: config stays the truth).

Expected change size: Slices 1-2 (Claude path, fake worker, docs) about 650 lines added and
20 removed; Slice 3 (OpenCode poll) about 110 added; Slice 4 (Codex mapping) about 40 added.
Total up to 800 added, 20 removed. This plan stays under 320 lines.

## Approach

1. One standalone hook script for every hook-driven system, told the event on its command line
   (`--event Stop`) rather than trusting each system's stdin field names; stdin supplies only
   `session_id` and event details. Rejected: per-system hook scripts (duplicate file writing);
   `hive status-hook` subcommand (needs `hive` on the pane's PATH and a config read per event).
2. `hive/activity.py` is pure: it reads files and takes the tmux facts (`pane_current_command`,
   screen text, `@hive_session`) as arguments, so `hive/launch.py` can import it without a cycle
   (`tmux` imports `launch`; `config` imports `launch`), and tests need no tmux. Callers in
   `workers.py` and `lifecycle.py` fetch the tmux facts.
3. Hook flags are appended at launch like the session args (`expand_pane` with a session id),
   never on the print-only path, so the status file is a per-launch fact and R4's resume command
   carries them for free. Rejected: a `{hook_args}` placeholder (inline JSON cannot sit inside a
   `sh -c '...'` quote); a settings file per pane (a second artefact to clean; wrappers get the
   `"$@"` idiom instead, Outline).
4. The tmux fallback needs history: a 30 s stability window across one-shot `hive list` calls
   lives in `state/screens/<name>.json` (hash, since). Rejected: `monitor-silence` (mutates tmux,
   clears on view); `window_activity` (per window; research B).
5. Gated systems are self-contained units: Slice 3 touches only `hive/drivers/opencode.py` and
   its tests; Slice 4 only `hive/drivers/codex.py` and its tests. A failed R1 gate drops the slice.

## Decisions

- D-R3.1 Status file: `<profile dir>/state/status/<pane name>.json`, written atomically (temp
  file plus `os.replace`), shape `{"state": "busy|done|blocked|dead", "event": "<native event>",
  "session_id": "<id or null>", "ts": <epoch seconds float>, "detail": "<notification type or
  null>"}`. `state`, `session_id`, `ts` are D10's fields; `event` and `detail` make `hive list`
  explainable and cost nothing. `cfg["state_dir"]` (`profile_dir() / "state"`) is set in
  `parse_config` and `lenient_config` next to `config_path`, the same way `queen.dir` is derived,
  so `status` works on a broken config too.
- D-R3.2 Hook command: `[sys.executable, <path of hive/hooks/status_hook.py>, <status file>,
  "--event", <name>]` per event. `sys.executable` for the reason `hive/queen.py:14-18` gives
  (a bare `python3` may be too old or absent in the pane); the script imports only the stdlib.
  The script always exits 0 and writes nothing to stdout: a non-zero exit from a Claude `Stop`
  hook blocks the agent from stopping, and stdout JSON is interpreted by the agent. Errors go to
  stderr. Missing or unparsable stdin still records the event with `session_id: null`.
- D-R3.3 Event mapping. Claude (hooks via `--settings`, research A3): `SessionStart -> done`
  (the agent waits for its first or next prompt; `detail` = `source`), `UserPromptSubmit ->
  busy`, `Stop -> done`, except `busy` when `background_tasks` or `session_crons` is non-empty
  (research A3: empty arrays mean truly done), `StopFailure -> blocked` (API error, needs a human), `Notification`
  with `notification_type` `permission_prompt` or `agent_needs_input` -> `blocked`, `idle_prompt`
  -> `done`, `SessionEnd -> dead`. Codex (hooks via `-c`, Slice 4): `SessionStart -> done`,
  `UserPromptSubmit -> busy`, `Stop -> done`, `PermissionRequest -> blocked`, `SessionEnd ->
  dead`. The mapping is one table in the hook script keyed by event name; an unknown event is
  recorded as `busy` with its name. Changes to R1's Claude `hook_args`: add `UserPromptSubmit` and
  `StopFailure`, extend the `Notification` matcher to `permission_prompt|idle_prompt|
  agent_needs_input`, and give each event its own command (the `--event` argument).
- D-R3.4 Precedence in `pane_state`: a driver poll result when the driver has one (OpenCode,
  `source=api`, `age=0`: a poll is current); else the status file when it exists (`source=hook`, `age` = now minus `ts`);
  else the tmux heuristic (`source=tmux`): `pane_current_command` in `SHELLS` (`sh bash zsh fish
  dash ksh` plus the basename of `cfg["pane_shell"]`'s first word) -> `dead`; screen hash
  unchanged for 30 s or more -> `quiet`; else `busy`; `age` = seconds since the screen last
  changed (0 on first sight). A stale file is prevented at the source: `setup_pane` deletes the
  pane's status and screen files before it types the command. Rejected: liveness overriding the
  file (a non-`exec` wrapper shows `sh` while the agent lives, research B).
- D-R3.5 OpenCode poll (Slice 3): `OpenCodeDriver.poll_state(env, session_id)` uses R1's
  `service_paths(env)` (D-R1.7) with a 2 s timeout: the id listed in `GET /api/session/active`
  -> `busy`; else a pending entry for it in `GET /api/permission/request` -> `blocked`; else
  `done`; service unreachable or no id -> `None` (fallback continues). No SSE (`/api/event`
  streams; a one-shot command cannot use it). The `Driver` protocol gains `poll_state(env,
  session_id) -> str | None`; Claude and Codex return `None`.
- D-R3.6 Output: the `pane` line of `hive list` gains ` state=<v> source=<s> age=<n>` after
  `system=`, before the optional ` waiting=<kind>`; `hive status` appends `  state=<v>
  source=<s> age=<n>` to the pane line of every pane that carries `@hive_name`. `waiting=` stays
  a separate fact: a dialog pane is `quiet` or `busy`, and the kind says why.
- D-R3.7 Fake worker for the live check: `tests/data/fake_worker.py`, a stdlib script that
  takes hive's appended `--session-id` and `--settings` flags, runs the hook commands it finds
  there with Claude-shaped JSON on stdin following `FAKE_EVENTS` (default `SessionStart
  UserPromptSubmit:3 Stop:6`; `Notification:permission_prompt:N` and `SessionEnd:N` are the
  other forms), then `exec`s `sleep 1d`. It exercises the real injection path end to end
  without an account. The D13 fake worker (`sh -c '...'`) ignores the appended flags and so
  exercises the tmux fallback.
- D-R3.8 Queen text: the `hive list` bullet in `hive/queen/CLAUDE.md` names the `state=` fields
  and calls them advisory (D16); nothing else in the queen dir changes (R6 owns the rest).

## Outline

Pointers are into `main` b5136c0 unless marked (R1), then into `feat/r1-claude-driver` 8ed901d.

- `hive/hooks/status_hook.py` (new, standalone, stdlib only): `main(argv) -> int` parsing
  `STATE_FILE --event NAME`; `read_input() -> dict` (stdin JSON, `{}` on error); `map_state(event,
  payload) -> (state, detail)` (table of D-R3.3); `write_status(path, record)` atomic, creating
  the parent dirs. Pattern for a standalone hook: `hive/queen/hooks/guard.py:1-40`. Package data:
  `pyproject.toml:27` gains `"hooks/*"`.
- `hive/activity.py` (new): `State(state, source, age)` dataclass; `QUIET_AFTER = 30`;
  `SHELLS`; `status_file(cfg, name)`, `screen_file(cfg, name)` under `cfg["state_dir"]`;
  `hook_cmd() -> list[str]` (D-R3.2, `importlib.resources.files("hive")`);
  `read_status(cfg, name) -> dict | None`; `reset_status(cfg, name)`; `pane_map(cfg) -> dict`;
  `tmux_fallback(cfg, name, current_command, screen, now) -> State` (updates the screen cache);
  `pane_state(cfg, name, system, env, session_id, current_command, screen, now=None) -> State`
  (D-R3.4); `state_fields(state) -> str` (`state=.. source=.. age=..`). Imports: stdlib,
  `hive.drivers`, `hive.reconcile`, `hive.util`.
- `hive/config.py:491-510` `parse_config` return dict and `:234-236` `lenient_config` return
  dict: `"state_dir": str(profile_dir() / "state")`.
- `hive/launch.py` (R1) `:43-58` `expand_pane`: after the session args, append
  `shlex.quote`d `driver.hook_args(hook_cmd(), status_file(cfg, pane.name))` when `session_id`
  is not `None`; nothing when it is. Gotcha: a `sh -c` wrapper swallows appended flags as `$0..`;
  the documented idiom is `sh -c 'VAR=x exec claude -n {name} --remote-control {name} "$@"' sh`.
- `hive/tmux.py` (R1) `:92-106` `setup_pane`: `reset_status(cfg, pane.name)` before `send-keys`.
- `hive/drivers/__init__.py` (R1) `:9-35`: protocol line `poll_state(env, session_id)`;
  `hive/drivers/claude.py` (R1) `:77-84` `hook_args`: events and matcher of D-R3.3, one command
  per event; `poll_state` returns `None`.
- `hive/workers.py` (R1) `:29-62` `cmd_list`: one `list-panes -s -F
  "#{pane_id}\t#{pane_current_command}\t#{@hive_session}"` call before the pane loop, then
  `pane_state(...)` with the screen already captured for `waiting_kind`; env is
  `{**cfg["env"], **pane.env}` and the system from `activity.pane_map(cfg)` (`{name: Pane}` over
  `desired_panes(cfg)`, queen included; `{}` when `cfg` has no `queen` key, the lenient case);
  a pane with no entry gets `system="claude"`, `env={}`.
- `hive/lifecycle.py:151-167` `cmd_status`: format gains `#{pane_id}\t#{@hive_name}\t
  #{@hive_session}` before `pane_title`; `capture-pane` per managed pane; system and env from
  the same `pane_map(cfg)` as `cmd_list`.
- `hive/queen/CLAUDE.md:9`: the bullet of D-R3.8.
- `tests/data/fake_worker.py` (new): D-R3.7; `tests/test_hooks.py`, `tests/test_activity.py`
  (new); `tests/test_cli.py` (R1) `:802-811` list tests gain the state fields;
  `tests/test_drivers.py` (R1) `:29-40` `test_hook_args_claude` per D-R3.3; `tests/test_args.py`
  (R1) gains the launch test. Stub pattern: `tests/test_cli.py` (R1) `ScreenTmux` at `:762-782`
  (answers `capture-pane`; extend it to answer `list-panes` with the state columns).
- `docs/idle-detection.md` (new; `tests/test_docs_links.py:14` already allows it): states and
  sources, the file layout, per-system event table, the wrapper idiom, the fake worker recipe,
  limits (stable means idle or blocked; a non-`exec` wrapper reads as `dead` only on the tmux path).
- Slice 3 (gated): `hive/drivers/opencode.py` `poll_state` (D-R3.5) with `urllib.request`,
  `tests/test_driver_opencode.py`. Slice 4 (gated): `hive/drivers/codex.py` `hook_args`
  (`-c 'hooks.<Event>=[{hooks=[{type="command",command="..."}]}]'` for the five events of
  D-R3.3 plus `--dangerously-bypass-hook-trust`) and `poll_state` returning `None`,
  `tests/test_driver_codex.py`. The R3 branch lands as one squash, so no intermediate state
  without the Codex `poll_state` ships.
- Invariants: `status_hook.py` imports nothing from `hive`; `activity.py` imports no `hive.tmux`;
  the hook never exits non-zero; `hive list` makes one `list-panes` and one `capture-pane` per
  pane (no extra round trips); the print-only `expand_pane` output is unchanged.

## Slices

1. Claude path end to end (unit A: `hive/hooks/status_hook.py`, `tests/test_hooks.py`,
   `pyproject.toml`; unit B: `hive/activity.py`, `tests/test_activity.py`, `tests/data/
   fake_worker.py`; unit C: `hive/launch.py`, `hive/tmux.py`, `hive/config.py`,
   `hive/drivers/__init__.py`, `hive/drivers/claude.py`, `tests/test_drivers.py`,
   `tests/test_args.py`; unit D: `hive/workers.py`, `hive/lifecycle.py`, `tests/test_cli.py`).
   Units C and D code against the `activity` signatures in the Outline (`pane_map` included).
   Delivers: every launch
   injects the hooks, the file appears on the first event, `list` and `status` show the state.
   Tests, A (run the script with `sys.executable`, stdin JSON, check the file):
   `status_hook_writes_file: Stop JSON -> state done, session_id set, ts within 5 s`;
   `status_hook_user_prompt -> busy`; `status_hook_stop_with_background_tasks -> busy`;
   `status_hook_stop_with_session_crons -> busy`;
   `status_hook_notification_permission -> blocked, detail permission_prompt`;
   `status_hook_notification_idle -> done`; `status_hook_agent_needs_input -> blocked`;
   `status_hook_stop_failure -> blocked`; `status_hook_session_end -> dead`;
   `status_hook_session_start -> done, detail startup`; `status_hook_unknown_event -> busy,
   event kept`; `status_hook_bad_stdin: garbage -> exit 0, file written, session_id null`;
   `status_hook_never_writes_stdout`; `status_hook_creates_dirs`; `status_hook_is_stdlib_only:
   no "hive" import in the source`; `status_hook_is_package_data: pyproject package-data has
   hooks/*`. B: `pane_state_prefers_hook_file_over_tmux`; `pane_state_poll_wins_over_file` (fake
   driver); `tmux_fallback_first_sight -> busy age 0`; `tmux_fallback_quiet: same screen, now +
   30 -> quiet age 30`; `tmux_fallback_changed_screen_resets_since`; `tmux_fallback_dead:
   current_command bash -> dead`; `tmux_fallback_pane_shell_basename_is_dead: pane_shell
   "/usr/bin/zsh -l", command zsh -> dead`; `reset_status_removes_both_files`;
   `state_fields_format -> "state=done source=hook age=42"`; `hook_cmd_uses_sys_executable_and_
   packaged_script`. C: `hook_args_claude: events SessionStart, UserPromptSubmit, Stop,
   StopFailure, Notification, SessionEnd; each command ends with --event <name>; Notification
   matcher permission_prompt|idle_prompt|agent_needs_input`; `expand_pane_appends_hook_flags:
   with a session id the command ends with --settings <json> after --session-id`;
   `expand_pane_print_path_unchanged: session_id None -> no --settings`;
   `hook_args_passed_on_every_launch: pane.args = ("--resume", id) -> command has both --resume
   and --settings`; `setup_pane_resets_status: stubbed tmux, pre-existing status file -> removed
   before send-keys`; `state_dir_in_cfg_and_lenient_cfg`. D: `list_prints_state_source_age:
   status file state=done -> pane line "... system=claude state=done source=hook age=<n>"`;
   `list_state_before_waiting: login screen plus no file -> "... state=busy source=tmux age=0
   waiting=login"`; `list_tmux_dead: current_command bash -> state=dead`;
   `status_prints_state: managed pane line ends with state=...; unmanaged pane line unchanged`;
   `status_lenient_config_prints_state` (broken config.toml, `state_dir` from the profile);
   `pane_map_includes_queen_and_is_empty_for_lenient_cfg`.
   Checkpoint: `uv run --frozen pytest -q`; test profile from the worktree (SAFETY CONTRACT;
   record `tmux -L hive list-panes -s -F '#{pane_id} #{@hive_name}'` before and after):
   `[queen] enabled = false`; type `fake` with `--command "python3 <worktree>/tests/data/
   fake_worker.py {name} --remote-control"` and type `plain` with the D13 command, both
   `--config-dir ~/.config/hive/profiles/test/claude --trust`; `up`; `list` at once: `fake`
   `state=done source=hook`, `plain` `state=busy source=tmux age=0`; after 4 s `fake` is `busy`,
   after 7 s `done`; after 31 s `plain` is `quiet age>=30`; `FAKE_EVENTS="SessionStart
   Notification:permission_prompt:2"` in `env` of a third type -> `blocked`; `tmux -L hive-test
   send-keys -t <plain pane> C-c` -> `plain` `state=dead source=tmux`; `status` shows the same;
   `cat ~/.config/hive/profiles/test/state/status/*.json`; `down`; production listing identical.
2. Docs and queen text (unit A: `docs/idle-detection.md`; unit B: `hive/queen/CLAUDE.md` bullet).
   Tests: `tests/test_docs_links.py` green; `tests/test_guard.py` unchanged and green (the bullet
   is prose). Checkpoint: `uv run --frozen pytest -q` and the Slice 1 fake-worker sequence
   still passing. User-run smoke (agents launch no real agent; the executor hands the user these
   commands and records the result as one `## Log` line, the R1 Slice 3 pattern): in the test
   profile, spawn type `cl` with the wrapper idiom of the Outline
   (`CLAUDE_CONFIG_DIR=$HOME/.config/hive/profiles/test/claude`), `up`, `list` shows
   `waiting=theme` (the injected `--settings` was accepted) and `ps -o args= -p $(pgrep -f
   'claude -n cl-test-1')` shows `--settings` with six hook events; `down`; `~/.claude.json`
   mtime unchanged. The optional token round is Q1.
3. OpenCode poll (only if R1 Slice 5 landed; one unit: `hive/drivers/opencode.py`,
   `tests/test_driver_opencode.py`). Tests with a fake `urlopen`: `poll_active -> busy`;
   `poll_pending_permission -> blocked`; `poll_idle -> done`; `poll_unreachable -> None`;
   `poll_timeout_is_2s`; `poll_uses_basic_auth_header`; `pane_state_opencode_source_api` (through
   `activity.pane_state`, asserting `age=0`). Checkpoint: `uv run --frozen pytest -q`. User-run
   check (one `## Log` line): test profile with the XDG `[env]` of R1 Slice 5: `spawn <dir>
   --type oc --system opencode`, `up`, `list` shows `state=done source=api`; `down`.
4. Codex hook mapping (only if R1 Slice 6 landed; one unit: `hive/drivers/codex.py`,
   `tests/test_driver_codex.py`). Tests: `codex_hook_args_events: SessionStart, UserPromptSubmit,
   Stop, PermissionRequest, SessionEnd, each -c value parses with tomllib and its command ends
   with --event <name>`; `codex_hook_args_bypass_trust_present`; `status_hook_codex_session_start:
   Codex-shaped stdin with session_id -> done, session_id set` (in `tests/test_hooks.py`);
   `codex_poll_state_is_none`. Checkpoint: `uv run --frozen pytest -q`. User-run check (one
   `## Log` line): test profile, fresh `CODEX_HOME` under the profile as in R1 Slice 6: `up`,
   `list` shows `system=codex` with a `source=hook` state once the `SessionStart` hook fired
   (`status/<name>.json` has a `session_id`); `down`.

## Verification

After the last slice: `uv run --frozen pytest -q` green; CI green on the branch; in
`--profile test`: the Slice 1 fake-worker sequence (`done`, `busy`, `done`, `blocked`, `quiet`,
`dead`) passes in one session, `hive list` prints `state=` for every pane, `hive status` too,
`down`; `~/.config/hive/profiles/test/state/` holds only `status/` and `screens/`; production
listing on this machine identical before and after. The user-run smokes of Slices 2-4 are
recorded in `## Log`, each as pass or as the deviation seen.

## Risks

- A hook event name Claude does not know could make it reject the whole `--settings` value and
  the pane would not start; the user-run Slice 2 smoke (`waiting=theme` reached, `ps` shows the
  flags) catches it, and the executor drops `StopFailure` if that is the culprit.
- `UserPromptSubmit` for a prompt sent through Remote Control is assumed to fire like a typed
  one (same session); unverified until Q1's token round.
- A non-`exec` wrapper on the tmux path reads as `dead`; the status file path is unaffected and
  the docs recommend `exec` (the Claude docs page already does).
- `hive list` writes a screen-cache file per pane per call; the queen polls often. Small JSON,
  atomic replace; acceptable.
- Codex `SessionStart` must fire before any prompt for R4 to find the id; R1 saw it (D-R1.1).

## Scope Notes

SAFETY CONTRACT of the parent binds every step: live checks only through
`uv run --frozen hive --profile test` from the worktree, never the default profile or socket
`hive`, here or on swarm; `send-keys` only to panes of the `hive-test` socket; production pane
listing recorded before and after; `config_dir` under the profile dir
(`.supervisor/memory/decisions/2026-10-27-hands-on-testing-uses-isolated-test-profile.md`).
Agents launch only the fake workers; every real-agent check (Slices 2-4) is the user's, and no
real agent is prompted unless the user answers Q1 yes. Files beyond the parent's R3 Owns that
this plan edits are listed in the planning report's `Amend parent:` lines (`hive/config.py`
`state_dir`, `hive/tmux.py` `setup_pane`, `hive/queen/CLAUDE.md` one bullet,
`tests/test_cli.py`, `tests/test_drivers.py`, `tests/test_args.py`, `tests/data/fake_worker.py`,
`tests/test_driver_opencode.py`, `tests/test_driver_codex.py`).

Parent decisions bind and are not reopened: D10 (file layout), D16 as amended (states, poll,
Codex hooks, `notify` rejected), D17 (R4 reads `session_id` from the status file), D13 (fake
worker). Out of scope: `stop --keep-session` and `spawn --resume` (R4), an event watcher,
a "stop idle" command, queen per system (R6), pi.

## Assumptions

- R1 lands `expand_pane(cfg, pane, session_id=None)`, `setup_pane` with `prepare_launch` and
  `@hive_session`, `Driver.hook_args(hook_cmd, state_file)`, `service_paths(env)` (OpenCode)
  as in `plan-r1-drivers.md` D-R1.1, D-R1.3, D-R1.7; checked by reading `main` when R3 starts,
  and this plan's pointers are re-resolved then.
- `#{@hive_session}` and `#{pane_current_command}` are available in `list-panes -F` on tmux
  3.2a and 3.5a (user options in formats exist since 3.0); checked by the Slice 1 live check.
- Claude passes `UserPromptSubmit` and `StopFailure` as hook event names in the settings `hooks`
  table (research A3 for the latter); checked by the Slice 2 smoke.
- `python3` is on the test pane's login-shell PATH for the fake worker; checked at the Slice 1
  live check (else the executor uses the worktree's `.venv/bin/python`).

## Open Questions

- Q1: run one real token round in the test profile (the user logs in once in
  `~/.config/hive/profiles/test/claude`, sends a short prompt by `send-keys`, `list` shows
  `busy` then `done`, and a permission prompt shows `blocked`)? Recommended: yes, once, after
  Slice 2, because it is the only check of the live event names on a real session; the package
  completes on the fake worker and smoke alone if the answer is no.

## Log

## Todo

- [ ] Slice 1: hook script, `activity.py`, `state_dir`, injection, `setup_pane` reset, Claude
      `hook_args` events, `list`/`status` fields, fake worker, unit tests, test-profile sequence
- [ ] Slice 2: `docs/idle-detection.md`, queen bullet, real-Claude smoke
- [ ] Slice 3: OpenCode `poll_state` (if R1 Slice 5 landed)
- [ ] Slice 4: Codex `hook_args` events (if R1 Slice 6 landed)
- [ ] Q1 answered; token round run if yes
- [ ] Verification passes; production hive unchanged
