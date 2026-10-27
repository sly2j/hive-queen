# Plan: hive queen 2.0 (program plan)

Release `2.x`. Parent plan; packages R0-R8 below. Roadmap: `.supervisor/roadmap.md`.
Planned against `main` 55e2298 (VERSION 1.23, `hive/cli.py` 1599 lines): CI exists
(`.github/workflows/test.yml`, pytest on ubuntu and macos, Python 3.11 and 3.13) and macOS is a
supported platform (`die_if_macos`, `hive/cli.py:1374`, gates the systemd commands).
Research: `.supervisor/working/research/2026-10-27-hive-queen-2.0-systems.md` (cited as
"research, section").

## Goal

Ship hive queen 2.0: workers on Claude Code, OpenCode and Codex CLI (the queen on Claude Code and
OpenCode, on Codex after a spike), removal of single instances, done/idle detection, session
resume, multi-node control over ssh, an isolated test profile, the rename to `hive-queen`, and
new-user docs. Every feature lands as its own squash-merged commit on `main`, validated in a test
hive, never against the production hive here or on swarm.

Non-goals: a state database (config.toml plus tmux stays the truth, except the per-pane status
and session files of R3/R4); a doc-site toolchain; PyPI publication (open question); pi and any
further agent system, and Codex remote access (both roadmap, research A1); launcher remove/rename;
macOS service install.

Expected change size: about 3500 lines added and 1000 removed across `hive/`, `tests/`, `docs/`,
`README.md`, `pyproject.toml`; the cli split moves about 1300 lines without changing behaviour.

## Approach

1. R0 adds the isolated test profile first, because every later package validates through it.
2. R1a splits `hive/cli.py` into modules per concern and a driver seam with one driver
   (`claude`), behaviour preserving except for accepting `system = "claude"`, so that packages
   touching disjoint concerns run as parallel executors in separate worktrees. Rationale: R0, R1,
   R2, R5, R6 all edit `cli.py` today; without the split every squash-merge conflicts. Rejected:
   parallel work on the monolith (conflicts in the same 200-line regions); splitting lazily per
   package (each package would move code the others depend on).
3. Waves after the split: R2 and R1 in parallel; then R5 and R3; then R4 and R6; then R8b docs
   polish; then R7 release. Each wave's packages own disjoint files (checked in `## Slices`).
4. R8a (docs skeleton) runs from day one next to R0 and R1a; it owns `README.md` and `docs/`
   except the one page each feature package writes.
5. Research findings bind the drivers (D15), done detection (D16) and the queen ports (D18).

## Decisions

Decisions the user and the supervisor made are in `## Scope Notes`. Lead decisions (dated
records in `## Log`):

- D1: split `cli.py` first (R1a), right after R0, behaviour preserving. Evidence: R0
  (config_home, lock, systemd, parser), R2 (stop, reconcile), R1 (expand, preflight, trust, queen
  command), R5 (parser, dispatch) and R6 (materialize_queen) all live in `hive/cli.py`. Tests
  patch `cli.tmux`, `cli.reconcile`, `cli.running_panes`, `cli.start_pane`, `cli.hold_lock` etc.
  by module attribute (`tests/test_cli.py:29-30,231-237,267,295-299,319-329,344,451-457`); the
  split updates those patch targets to the owning module; the CLI surface (`hive --help`, exit
  codes, output) stays byte-identical.
- D2: R0 lands before the split, in the monolith (about 150 lines); R1a then moves that code
  with the rest. Reason: R0 is small and every later package needs it for live validation.
- D3: profile model. `hive --profile NAME` (global option) or `HIVE_PROFILE=NAME` (option wins).
  The default profile is today's `<config_home>/hive/`; a named profile lives in
  `<config_home>/hive/profiles/<name>/` with its own `config.toml`, `.lock`, `queen/` and
  `state/`. Name regex `[a-z0-9][a-z0-9-]*`, `default` reserved for the default profile.
  Defaults for a named profile: `prefix = <name>`, `session = <name>-agents`,
  `tmux_socket = hive-<name>`. Rejected: `XDG_CONFIG_HOME` juggling (the guard blocks env
  prefixes; the unit would need a second XDG tree); `--config PATH` (no place for state and
  queen dir).
- D4: profile safety invariants (exit 2). A named profile whose effective `tmux_socket` equals
  the default profile's effective socket (default config read leniently, `hive` when unreadable
  or absent) is refused, in `parse_config` and again in `lenient_config`
  (`hive/cli.py:235-262`, which `down` and `status` use on a broken config), so no code path of a
  named profile can reach the production socket. `hive restart`, `install-service`,
  `uninstall-service` and `systemd_unit_active` use `hive-<name>.service` for a named profile and
  never `hive.service`; `install-service` for a named profile writes
  `ExecStart={exe} --profile <name> up` and the matching `ExecStop`; the macOS gate
  (`die_if_macos`) is unchanged. Every pane of a named profile gets `export HIVE_PROFILE=<name>`
  in its shell line, so a queen or worker inside the test hive addresses the test hive with plain
  `hive` commands and the guard needs no change (it keeps blocking `--profile` and env prefixes).
- D5: `[queen] enabled = true|false` (default true) is added in R0: it makes a test hive cheap
  and is the explicit per-node queen-less option R5 needs (swarm already runs its own queen,
  research C). When disabled: `desired_panes` has no queen; `materialize_queen` is skipped; an
  existing queen pane is surplus and stopped by reconcile (today `plan` never stops the queen,
  `hive/reconcile.py:58`; the rule becomes "never stop an enabled queen"). Empty hive: `cmd_up`
  (`hive/cli.py:776`) creates the session from the first desired pane, queen or worker; with no
  desired pane at all `hive up` prints `nothing to start: queen disabled and no agents` and exits
  0 without a session, and `hive list` shows `running=no`. The test recipe therefore spawns
  before `up` (spawn edits config without a session, `after_edit` reconciles only when up).
- D6: per-instance removal (R2) uses an explicit per-agent `indices = [2, 3]` list, exclusive
  with `count`. `desired_panes` uses `indices` when present, else `range(1, count+1)`.
  `hive stop` removes indices; a remaining set contiguous from 1 is written back as `count`, else
  as `indices`. `hive spawn TYPE -n N` fills the lowest free indices (today's name reuse on
  stop-then-spawn is kept). Target rule for `hive stop TARGET... [-n N] [--index N...]`: a TARGET
  equal to a configured type is a type (today's behaviour, highest index first); otherwise it is
  parsed as an instance name `<type>-<machine>-<N>`; `TYPE --index N` is the unambiguous form and
  the one the queen is told to use, because type names may contain hyphens (`TYPE_RE`,
  `hive/cli.py:47`) and could equal an instance name. Supersedes "N stays derived 1..count,
  never stored" in `.supervisor/memory/decisions/2026-10-22-instance-naming-and-queen-rename.md`:
  N is still derived, from `count` or `indices`. Rejected: tombstones or a pane-id map;
  renumbering survivors (renames running RC sessions).
- D7: driver seam. Config key `system` at `[defaults]`, `[[launchers]]`, `[[agents]]` and
  `[queen]`, precedence agent > launcher > defaults, default `claude`; R1a adds the key with
  `claude` as the only valid value (the one behaviour change of the split). `hive/drivers/
  __init__.py` holds the `Driver` protocol, `DRIVERS` and `get_driver(name)`;
  `hive/drivers/claude.py` holds today's Claude-specific code. R1 adds `opencode.py` and
  `codex.py` and implements every protocol method for every driver from the research, including
  `hook_args`, `session_args`, `resume_args`, `queen_extras` and `supports_queen`, so R3, R4 and
  R6 read drivers and only R3 (hook fixes) and R6 (`supports_queen` flip for codex/opencode) edit
  them, in different waves.
- D8: multi-node (R5) hive-side: `[[nodes]]` with `name`, `host`, `hive` (remote executable,
  default `hive`; docs recommend `/home/<user>/.local/bin/hive`, research C: non-login bash has
  no `~/.local/bin`), optional `profile`, `description`. `hive --node NAME <cmd...>` runs
  `ssh -o BatchMode=yes -o ConnectTimeout=10 <host> -- <shlex.join([hive, "--profile", P, *cmd])>`
  with stdio passed through; the remote exit code is returned, 255 becomes exit 1 with
  `node <name> unreachable`; `attach` with `--node` is refused (exit 2). Safety: from a named
  local profile a node must name a non-default remote profile (`profile` present and not
  `default`), so a test hive can never drive a production remote. `hive nodes` lists the table; nodes are
  added by editing config.toml (no `nodes add`: registering a node is user setup, not a queen
  action). The guard allows `--node NAME` / `--node=NAME` (NAME matching `LAUNCHER_NAME_RE`) as
  the only global option and applies the subcommand rules to the shifted tokens. Queen-less node =
  `[queen] enabled = false` in that node's own config (D5). Rejected: the queen running ssh
  (breaks the single-`hive`-command guard); remote tmux over ssh (needs a tty).
- D9: swarm dev builds live in `/home/sjoosten/dev/hive-queen` on swarm (git clone, branch
  checked out, `uv sync`), executable `/home/sjoosten/dev/hive-queen/.venv/bin/hive`, used only
  with `--profile test`; the installed tool (1.19) is never touched.
- D10: per-pane files under `<profile dir>/state/`: `status/<name>.json` written by injected
  hooks (R3: `state`, `session_id`, `ts`) and `sessions.json` (R4: name to session id). The
  config stays the only source of desired state. Reason: a session id must survive pane death
  (research, implications 4-5).
- D11: docs ownership. Feature packages never edit `README.md`; each owns one docs page (R0
  `docs/test-profile.md`, R2 `docs/commands.md`, R1 `docs/systems/*.md`, R3
  `docs/idle-detection.md`, R4 `docs/resume.md`, R5 `docs/multi-node.md`, R6 `docs/queen.md`,
  R7 `docs/upgrade.md`). R8a creates every other page and leaves these to their packages (its
  README links to them are allowed to dangle until the package lands); R8b polishes everything
  before R7.
- D12: release mechanics (R7). Dist name `hive-queen`, import package stays `hive`, command stays
  `hive`, so `hive.cli:main` is unchanged; `pyproject.toml` packages list becomes
  `["hive", "hive.drivers"]` in R1a (an explicit setuptools list does not include subpackages).
  `get_version` (`hive/cli.py:1421`, `pkg_version("hive")`) switches to `hive-queen` in R7 and
  `uv.lock` is regenerated. The release commit on `main` is made with `--no-verify` so the
  pre-commit hook (`.githooks/pre-commit`, derives from `HEAD:VERSION`) does not overwrite
  `VERSION` = `2.0`; tag `v2.0`; later commits bump `2.1`, `2.2` by the hook unchanged. GitHub
  rename via `gh repo rename hive-queen` (redirects the old URL), then `git remote set-url`.
  Install path stays the git URL.
- D13: test-hive worker command before R1 is a fake worker,
  `sh -c 'echo {name} --remote-control; exec sleep 1d'`, with `config_dir` under the profile dir
  so trust seeding never touches `~/.claude.json`; it serves before and after R1 (system `claude`).
- D14: accepted sequencing: R5 waits for R2 (both edit `hive/config.py`), R3 waits for R1 and
  lands before R4 (R4 reads the session id from R3's status file), R6 waits for R5 (guard and
  CLAUDE.md text) and R3 (drivers). Rejected: full parallelism with same-file conflicts.
- D15: drivers from research. Claude: default command unchanged plus `--session-id {session_id}`
  (hive assigns UUIDs, research A2), `required_tokens = ("--remote-control",)`, hooks via
  `--settings <json>` built per pane and passed on every launch including resume (not restored by
  `--resume`, research A2), `resume_args = ["--resume", id]`, `queen_extras` as today,
  `supports_queen = True`. OpenCode: target v2.0.x; `hive spawn` probes `opencode --version` and
  exits 2 with a clear message on v1; launch `opencode --auto -s {session_id}`-style with
  `--standalone` per pane (v2 shared service otherwise owns sessions), remote through
  `serve`/`web`/`pair` on localhost (docs tell the user to ssh-forward), `required_tokens = ()`,
  done signal from the pane's server API (research A3), config dir via XDG plus `--standalone`,
  instruction file `AGENTS.md`, `supports_queen` true after R6. Codex: unattended and trust
  flags plus `-c` hook overrides and the hook-trust bypass for hive's own hooks per research A3-A4
  (exact flags in the R1 child plan), no launch-time name (hive sets the pane title and documents
  `/rename`), session id discovered from the `SessionStart` hook, `resume_args = ["resume", id]` (subcommand form), `required_tokens = ()`,
  `config_dir_env = CODEX_HOME`, instruction file `AGENTS.md`, `supports_queen` false until the
  R6 spike passes. Each driver records the version observed (`versions` tuple) and `hive list`
  prints `system=`. Unverified items (fresh-config-dir onboarding dialogs, Claude RC consent
  prompt, Codex `-c` hook injection, OpenCode TUI plus browser on one session) are R1 spike
  steps before its slices.
- D16: done detection (R3). Primary: per-driver native events written by a hive hook script to
  `status/<name>.json` with `state in {busy, done, blocked, dead}`; the per-event mapping per
  driver is in the R3 child plan (research A3; OpenCode via the server API poll, no hook
  injection). Fallback when no status file exists: `capture-pane` hash
  stable for 30 s and `pane_current_command` not a shell gives `quiet`, a shell gives `dead`,
  else `busy` (research B: stable means idle or blocked, so the fallback never claims `done`).
  `hive list` prints `state=<value> source=hook|tmux age=<s>`; `hive status` prints it per pane.
  The queen's instructions call the field advisory.
- D17: resume (R4). The session id of a live pane is the status file's `session_id` when
  present, else the pane option `@hive_session` set at launch (R1), so a Claude worker is
  resumable without any hook. `hive stop ... --keep-session` reads it before killing the pane
  and records it in `sessions.json` instead of forgetting it; `hive spawn TYPE --resume NAME` restarts that
  instance with `driver.resume_args(id)` placed at `{args}`, keeping all other launch flags
  (hooks included). Codex and OpenCode ids come from the status file.
- D18: queen per system (R6). Layout `hive/queen/<system>/` (claude: today's `CLAUDE.md`,
  `settings.json`, `hooks/guard.py`; opencode: `AGENTS.md` and an `opencode.json` with the v2
  ordered `{action, resource, effect}` permission rules on the `shell` action allowing only
  `hive ...` and denying the rest, research A5 v2, plus a plugin shim for the `ask` cases; the
  spike verifies allow and deny behaviour on v2 before the OpenCode queen is enabled; codex:
  `AGENTS.md`, `.codex/` hooks config) over a shared `hive/queen/guard_core.py` (system-neutral `check_bash`
  and config allowlists extracted from `guard.py:141-191`, copied into each queen dir so the
  hooks stay standalone). `hive/queen.py` materializes per system. Codex: PreToolUse cannot
  return `ask` (research A5), so R6 starts with a spike: a Codex queen in the test hive must
  allow `hive list`, deny `hive list; ls`, and deny every command that would be `ask` on Claude
  (`down`, `restart`, `spawn --trust`, `spawn --env`, `roots add`, `launchers add`),
  with the user told to run those by hand. If a spike fails, R6 does not complete: it returns
  `blocked` with Q2 (below) for the user (the user's decision, Scope Notes).

## Outline

Pointers are into the current tree (`hive/cli.py` is 1599 lines).

### R0 test profile (in the monolith; R1a moves it)
- `hive/cli.py:88-93` `config_home()`, `config_path()`: add `profile_name() -> str | None`
  (option, then `HIVE_PROFILE`), `profile_dir() -> Path`, and route `config_path`, lock
  (`:97-128`), queen dir (`:442`) through `profile_dir()`. `build_parser` `:1460` gets
  `--profile NAME`; `run` `:1545` stores it before dispatch.
- `hive/cli.py:291-450` `parse_config`: profile defaults for `prefix`, `session`, `tmux_socket`
  (`:297-304`); `default_socket() -> str` reads the default profile leniently;
  `refuse_socket_collision(sock)` called from `parse_config` and from `lenient_config` `:235-262`
  after `pick("tmux_socket", ...)`; `[queen] enabled` in `QUEEN_KEYS` `:42`.
- `hive/cli.py:34` `UNIT_NAME` becomes `unit_name() -> str`; `systemd_unit_active` `:812`,
  `cmd_restart` `:819`, `unit_path` `:1333`, `UNIT_TEMPLATE` `:53-72`, `cmd_install_service`
  `:1380`, `cmd_uninstall_service` `:1403`; `die_if_macos` `:1374` untouched.
- `hive/cli.py:523` `shell_line`: export `HIVE_PROFILE` for a named profile.
- `hive/cli.py:771-797` `cmd_up`: `first = desired[0]` becomes "first desired pane or the
  nothing-to-start exit"; `materialize_queen` `:685` only when enabled. `hive/reconcile.py:41-56`
  `desired_panes` skips a disabled queen; `plan` `:58` takes `queen_name=None` when disabled.
  `cmd_list` `:862` prints `queen enabled=no`. `hive/config.example.toml` documents `enabled` and
  the profile defaults.
- Gotchas: `tests/conftest.py` deletes `HIVE_PROFILE` too; `tests/test_tmux.py` keeps explicit
  sockets and gains a profile test on a second socket.

### R1a cli split (module map; names keep their current signatures)
- `hive/cli.py` (under 250 lines): `EPILOG`, `BROKEN_CONFIG_NOTE`, `build_parser` (calls each
  module's `add_parser(sub)` in today's order so `--help` is identical), `LOCKED`, `run`, `main`,
  `--profile` handling.
- `hive/util.py`: `die` `:75`, `warn` `:80`, `quote` `:853`, `positive_int` `:1428`, `depth_int`
  `:1438`, `get_version` `:1421`; imports nothing from `hive`.
- `hive/config.py`: `:84-93` paths and `ConfigError`, `:131-450` validation split into
  `parse_defaults`, `parse_agents`, `parse_launchers`, `parse_queen`, `parse_env`, plus
  `parse_config` assembling them; `system` key (D7); `cmd_init` `:1313`; constants `:34-50`
  except driver constants.
- `hive/lock.py`: `:96-128`.
- `hive/tmux.py`: `:494-633` (`tmux_env`, `tmux`, `session_running`, `shell_line`,
  `running_panes`, `window_ids`, `expand_pane`, `setup_pane`, `start_pane`).
- `hive/reconcile.py` gains `parse_name` `:535`, `parse_legacy_name` `:549`.
- `hive/launch.py`: `:452-491` (`queen_command_line`, `default_shell`, `expand`,
  `expand_command`), `preflight` `:649-669`, `check_launcher_command` `:958`; both consult
  `driver.required_tokens` instead of the literal `--remote-control`.
- `hive/drivers/__init__.py`, `hive/drivers/claude.py`: `DEFAULT_QUEEN_COMMAND` `:44`,
  `QUEEN_TOOLS` `:46`, `CLAUDE_SESSION_ENV` `:496`, `CONFIG_DIR_ENV_MSG` `:183`, the
  `--remote-control` rule `:655-658,959-960`, trust glue `:635-646,857-859,1023-1036`, queen
  files list `:689-694`, `hive/inspect.py:19` `MATCH_RE`. `hive/trust.py` stays and is called
  from the driver. `pyproject.toml` packages list gains `hive.drivers` (D12).
- `hive/queen.py`: `queen_settings` `:671`, `materialize_queen` `:685`, `QUEEN_HEADER` `:51`,
  queen dir `:442`.
- `hive/lifecycle.py`: `reconcile` `:704`, `cmd_up` `:771`, `cmd_down` `:800`, `cmd_restart`
  `:819`, `cmd_reconcile` `:1162`, `cmd_status` `:828`, `cmd_attach` `:847`.
- `hive/workers.py`: `cmd_list` `:862`, `edit_config` `:892` to `expand_config_dir` `:951`,
  `cmd_spawn` `:1056`, `cmd_stop` `:1147`, `ensure_trust` `:1023`.
- `hive/launchers.py`: `:963-1052` helpers, `cmd_launchers` `:1225-1304`, `cmd_discover`
  `:1305`, `cmd_inspect_launcher` `:1166`.
- `hive/roots.py`: `cmd_dirs` `:1170`, `same_dir` `:1174`, `cmd_roots` `:1186`.
- `hive/service.py`: `:812-816`, `:1333-1420`, `UNIT_TEMPLATE`.
- Invariants: no import cycles (today `cli` imports six modules, nothing imports `cli`);
  `util` and `paths` import no `hive` module; `guard.py` stays standalone; `python -m hive.cli`
  and `hive.cli:main` keep working; tests patch the owning module.
- `Driver` protocol (illustrative shape; R1a implements `claude` only):
  ```
  name: str; versions: tuple[str, ...]; default_command: str
  required_tokens: tuple[str, ...]; env_scrub: tuple[str, ...]; config_dir_env: str | None
  unattended_args: list[str]; instructions_file: str; supports_queen: bool
  probe(binary: str) -> str | None                      # version, R1
  trust_state(root, config_dir) -> TrustState; seed_trust(...); looks_like_prompt(text) -> bool
  session_args(session_id: str) -> list[str]; resume_args(session_id: str) -> list[str]
  hook_args(hook_cmd: list[str], state_file: Path) -> list[str]   # R3 consumes
  queen_extras(command: str, args: list[str]) -> str
  inspect_pattern: re.Pattern
  ```

### R2 per-instance removal
- `hive/configedit.py:53` `set_count(text, type_, n)`: add `set_indices(text, type_, indices)`
  writing `indices = [..]` and dropping `count` (or the reverse), following `set_count`'s
  line-preserving pattern; `verify` unchanged.
- `hive/config.py` `parse_agents`: `indices` in `AGENT_KEYS`, distinct positive ints, exclusive
  with `count`; `agent_indices(agent) -> list[int]`.
- `hive/reconcile.py:41` `desired_panes`: iterate `agent_indices`. `plan` `:58` unchanged;
  adoption (`running_panes`, `hive/cli.py:562`) adopts by desired name, so a sparse set adopts
  only desired indices.
- `hive/workers.py` `cmd_stop`: targets per D6; `cmd_spawn`: lowest free indices; `cmd_list`:
  `indices=` when sparse. `hive/queen/CLAUDE.md:11,26`: `hive stop TYPE --index N`.

### R1 drivers
- `hive/drivers/opencode.py`, `codex.py` per D15; `hive/drivers/__init__.py`
  `DRIVERS` gains them. `hive/launch.py` `expand_command`: `{session_id}` placeholder,
  `driver.unattended_args`, `driver.session_args`. `hive/trust.py`: Claude only, called by
  `drivers/claude.py`; Codex trust pre-seed via `-c` (no file write); OpenCode: none.
  `hive/inspect.py`: pattern per driver. `hive/workers.py` is not edited (superseded by the R1 child plan): `cmd_spawn` already
  calls `ensure_trust` and `preflight`, which call the driver.

### R5 multi-node
- `hive/config.py`: `parse_nodes`, `NODE_KEYS`, `nodes` in `TOP_KEYS` `:36`.
- `hive/nodes.py` (new): `node_argv(node, profile, argv) -> list[str]`, `run_remote(node, argv)
  -> int`, `cmd_nodes`, `add_parser(sub)`. `hive/cli.py` `run`: `--node` dispatches
  to `run_remote` before loading the local config (lenient read of the node table only).
- `hive/queen/hooks/guard.py:162-165` option rule and `:141-191` `check_bash`: `--node NAME`
  prefix; `hive/queen/CLAUDE.md`: "Remote nodes" section. `tests/test_guard.py:288` keeps
  passing for other options.

### R3 done detection
- `hive/hooks/status_hook.py` (new, standalone, package data): reads the hook JSON on stdin
  (Claude and Codex share `session_id`, `hook_event_name`/`type`), writes
  `status/<name>.json`. `hive/activity.py`: `pane_state(cfg, driver, pane) -> State`,
  `tmux_fallback(cfg, pane)`, `opencode_poll(port)`. `hive/launch.py` `expand_command` appends
  `driver.hook_args(...)` for every launch. `hive/workers.py` `cmd_list` pane line and
  `hive/lifecycle.py` `cmd_status` print the state. `pyproject.toml` package data gains
  `hooks/*`.

### R4 resume
- `hive/sessions.py` (new): `load(profile_dir)`, `record(name, session_id)`, `forget(name)`,
  `current_id(cfg, pane)` (status file, else `@hive_session`). `hive/workers.py`:
  `--keep-session` on `stop`, `--resume NAME` on `spawn`; the resume args go to `{args}`.

### R6 queen per system
- `hive/queen/guard_core.py`, `hive/queen/<system>/*`, `hive/queen.py` `materialize_queen(cfg)`
  dispatching on `[queen] system`; `hive/drivers/codex.py` and `opencode.py` `supports_queen`
  and `queen_extras`; `pyproject.toml:28` package-data globs.

### R7 release
- `pyproject.toml` name and URL; `hive/util.py` `get_version` dist name; `uv.lock`; `VERSION`;
  `docs/upgrade.md`; tag `v2.0`.

## Slices

Each slice is a wave; a package's own acceptance is in its block. Units in a slice run as separate
executors in separate worktrees (`repo-workflow`), each squash-merged to `main` when its tests,
CI and test-hive validation pass. Owns sets within a wave are disjoint.

1. Wave 1: R0 (executor) and R8a (writer). Tests: R0 block. Checkpoint:
   `uv run --frozen pytest -q`; `gh run list --branch <branch> --limit 1` shows success; the
   test-hive recipe (Scope Notes) runs end to end; `wc -l README.md` under 150 and the link check
   (`python3 -c` over `docs/**/*.md`, written by R8a as `tests/test_docs_links.py`) passes.
2. Wave 2: R1a (executor), as soon as R0 lands (R8a may still run). Tests: existing suite
   with patch targets moved; `test_cli_help_unchanged` (golden `tests/data/help.txt` captured
   before the split) -> identical; `test_wheel_has_drivers: uv build, install into a scratch
   venv outside the checkout, python -c 'import hive.drivers.claude' -> ok`. Checkpoint:
   `uv run --frozen pytest -q`; CI success; recipe passes unchanged; `wc -l hive/cli.py` under 250.
3. Wave 3: R2 and R1 (executors). Checkpoint: `uv run --frozen pytest -q`; CI success; recipe
   plus the Validate steps of both blocks (`hive --profile test stop TYPE --index 1` keeps `-2`;
   one worker per system starts with `config_dir` under the profile).
4. Wave 4: R5 and R3 (executors). Checkpoint: `uv run --frozen pytest -q`; CI success;
   `uv run hive --profile test --node swarm list` returns the swarm test hive's records; `hive
   --profile test list` prints `state=` for every pane.
5. Wave 5: R4 and R6 (executors). Checkpoint: `uv run --frozen pytest -q`; CI success; `spawn
   --resume` restores a worker (capture-pane shows the resumed session); one real queen per
   supported system passes the guard checks of D18.
6. Wave 6: R8b (writer), then R7 (executor). Checkpoint: `## Verification`.

## Verification

After R7: fresh clone of `hive-queen`, `uv sync`, `uv run --frozen pytest -q` green; CI green on
`main`; `UV_TOOL_DIR=<scratch> uv tool install .` gives a `hive` that prints `hive 2.0` from
package metadata (no checkout `VERSION` on its path); test hive on this machine with `--profile
test`: spawn one worker per supported system (`config_dir` under the profile), `up`, `list`
shows `state=` and `system=` per pane, `stop TYPE --index 1` of a two-instance type keeps
instance 2, `stop --keep-session` then `spawn --resume` restores a worker, `--node swarm list`
reaches the swarm test hive, `down`; `git tag` lists `v2.0`; production hives on both machines
unchanged (`tmux -L hive list-panes -s -F '#{pane_id} #{@hive_name}'` identical before and
after).

## Risks

- A real-tmux test that omits `tmux_socket` would hit the default socket; R0 adds a test that
  every `tests/` config fixture names a socket, and conftest deletes `HIVE_PROFILE` and `TMUX`.
- The split can change behaviour through import order or a missed module global used by tests;
  the identical-help test, the wheel import test and the unchanged suite catch it.
- R2: sparse `indices` and legacy adoption (`parse_legacy_name`) interact; tests cover
  adopt-with-indices.
- R1: first launch in a fresh config dir may show onboarding or consent dialogs (Claude RC
  consent, OpenCode `auth`, Codex trust) that block a pane; the R1 spike lists them and the
  driver's `looks_like_prompt` reports `waiting=` for each; docs tell the user to attach once.
- R1: OpenCode v1 on a host (swarm's generation is unchecked) fails the version probe; the
  message names the install command.
- R3: `--settings` hook injection changes a Claude worker's settings precedence; the hook file
  only adds `Stop`/`Notification`/`SessionStart`/`SessionEnd` entries. Claude `auto` mode pauses
  after repeated classifier blocks (research A4); the `Notification` hook should surface it as
  `blocked`, unverified.
- R5: ssh host-key prompts fail fast under `BatchMode=yes` (255, reported as unreachable with a
  hint to connect once by hand).
- R6: the Codex guard port may fail its spike (no `ask`, hook coverage gaps); handled by D18.
- Token cost: R6 validation starts real queens in the test hive; one per system, torn down in the
  same session.
- Research incident: the OpenCode service password on this machine was exposed in a research
  transcript; rotating it is a user action, listed in the report.

## Scope Notes

SAFETY CONTRACT, binding on every package and every stage: the supervisor's own session runs
inside the production hive on this machine (`TMUX=/tmp/tmux-1002/hive`). No package may run
`hive up`, `down`, `restart`, `stop`, `spawn` or `reconcile`, nor `tmux kill-*`, against the
default profile or the `hive` socket, on this machine or on swarm. Live validation happens only
through a named test profile (R0): `uv run hive --profile test ...` from the worktree locally,
and on swarm through the dev venv of D9 with `--profile test`. Until R0 has landed, the only live
checks are the existing pytest tmux tests on `hive-test-<pid>` sockets. Every test-profile agent,
launcher and queen sets `config_dir` (or the driver's config-dir equivalent) under the profile dir
so trust seeding never writes `~/.claude.json`, `~/.codex` or `~/.config/opencode`. Never run
`hive attach` from inside the hive. Record the production pane listing
(`tmux -L hive list-panes -s -F '#{pane_id} #{@hive_name}'`) before and after a validation
session and report any difference. R0 therefore blocks every package that needs live validation;
packages whose validation is pytest-only (R1a, R8a) may start concurrently.

Decisions the user made, not to be reopened (memory entries under
`.supervisor/memory/decisions/2026-10-27-*.md`): repo and dist `hive-queen`, command `hive`,
upgrade note; Codex CLI and OpenCode must-have, others only with a proven remote-access story
(research: pi has none official, Codex's is experimental and not for Linux, so pi goes to the
roadmap and Codex ships as a worker without remote access); the queen on every supported system
(Codex via the D18 spike); squash-merge and push each feature when tests, CI and test-hive
validation pass, stopping only for genuine forks and the final release. Supervisor defaults in
force: `1.x` bump scheme, `2.0` set at release, tags from then on; short README plus plain
`docs/`; nodes modeled hive-side over ssh; dev builds on swarm in an isolated venv; all live
testing in an isolated test profile.

Out of scope: PyPI publication (Q1), launcher remove/rename, macOS service install, migrating
existing production configs (the default profile keeps today's layout).

Test-hive recipe (R0 onward), from a worktree:
```
uv run hive --profile test init            # writes profiles/test/config.toml
# edit: [queen] enabled = false; [defaults] command = fake worker (D13);
#       config_dir = "<profile dir>/claude" (or the driver's equivalent)
uv run hive --profile test spawn ~/some/dir --trust -n 2    # config only: no session yet
uv run hive --profile test up && uv run hive --profile test list
uv run hive --profile test stop some-dir -n 1 && uv run hive --profile test list   # --index from R2 on
uv run hive --profile test down            # kills only the hive-test server
```

## Assumptions

- `gh` is authenticated for `sly2j` on this machine; checked with `gh auth status` in R7.
- swarm accepts non-interactive ssh; checked at planning time (`BatchMode` returns 0) and again
  in R5 before any remote command.
- tmux 3.2a (here) and 3.5a (swarm) both support `set-option -p` and `@user` options; checked by
  the existing tmux tests on both machines in R0 (swarm venv) and R5.
- Codex CLI 0.164.0 is installed here, not on swarm; OpenCode v2.0.14 here, generation on swarm
  unchecked; checked by `which` and the version probe at R1 validation (installs on swarm are a
  user action if needed).

## Work Packages

Status values: `<stage due next>` | `blocked: <stage>: <why>` | `done`. Every package inherits the
SAFETY CONTRACT and the docs ownership rule (D11). "Validate" is the test-hive step. Every code
package also requires the CI workflow green on its branch push (both OSes, both Pythons) before
the squash-merge.

### R0: Test hive profile
- Goal: a named profile isolates config, lock, queen dir, state, tmux socket, names and systemd
  unit; done when the recipe in Scope Notes runs on `hive-test` with the production hive untouched.
- Owns: `hive/cli.py`, `hive/reconcile.py`, `hive/config.example.toml`, `tests/conftest.py`,
  `tests/test_config.py`, `tests/test_tmux.py`, `tests/test_cli.py`, `tests/test_reconcile.py`,
  `docs/test-profile.md`.
- Deps: none
- Stages: execute
- Status: done
- Lead: executor
- Accept: `test_profile_paths: --profile t -> <xdg>/hive/profiles/t/config.toml and .lock`;
  `test_profile_env_vs_option: HIVE_PROFILE=a plus --profile b -> b`; `test_profile_defaults:
  named profile without keys -> prefix t, session t-agents, socket hive-t`;
  `test_profile_socket_collision: named profile with tmux_socket = "hive" -> exit 2`;
  `test_lenient_down_refuses_collision: named profile, malformed config with tmux_socket =
  "hive" -> down exits 2 and no tmux call`; `test_profile_unit_name: --profile t install-service ->
  hive-t.service with ExecStart ... --profile t up`;
  `test_restart_named_profile_never_checks_hive_service: fake systemctl records is-active
  hive-t.service only`; `test_install_service_named_profile_on_macos: darwin -> exit 1 as today`;
  `test_queen_disabled: enabled=false -> desired_panes has no queen, plan stops a running queen
  pane, list prints queen enabled=no`; `test_up_empty_hive: enabled=false, no agents -> exit 0,
  message, no tmux call`; `test_up_first_pane_is_worker: enabled=false, one agent -> new-session
  from the worker`; `test_pane_exports_profile: shell_line in profile t contains export
  HIVE_PROFILE=t`; `test_invalid_profile_name: --profile Bad.name -> exit 2`;
  `test_fixtures_name_a_socket: every tests/ config text contains tmux_socket`; tmux test: a
  second profile on socket `hive-test-<pid>-b` runs `spawn`, `up`, `list`, `down` without
  touching the first. Validate: recipe in Scope Notes here, then on swarm from the D9 venv (its
  setup is part of this package, once).
- Artifacts: ->

### R8a: Docs skeleton and short README
- Goal: `README.md` under 150 lines pointing into `docs/`, with every current README section
  moved to a topic page; done when the link check passes and no content is lost.
- Owns: `README.md`, `docs/` except the feature pages of D11, `tests/test_docs_links.py`:
  `getting-started.md`, `configuration.md`, `launchers.md`, `trust.md`, `service.md` (systemd
  and macOS), `troubleshooting.md`, `development.md`.
- Deps: none
- Stages: write
- Status: done
- Lead: writer
- Accept: `tests/test_docs_links.py` checks relative links and anchors in README and `docs/`,
  with the D11 feature pages allowed to be absent until their package lands; the current README
  sections `README.md:9-441` each map to a page (the writer lists the mapping in its report);
  README states the name `hive queen` (URL changes wait for R7); plain Markdown only. Validate:
  none (docs only); `uv run --frozen pytest -q` green.
- Artifacts: ->

### R1a: Split cli.py into modules and a driver seam
- Goal: `hive/cli.py` under 250 lines, the module map in Outline, one `claude` driver and the
  `system` key; done when behaviour is identical except that `system = "claude"` is accepted.
- Owns: every file under `hive/` except `hive/queen/*`, `hive/configedit.py`, `hive/dirs.py`,
  `hive/paths.py`; all `tests/*.py` except `tests/test_docs_links.py`; `tests/data/help.txt`;
  `pyproject.toml` (the module map is documented by R8b).
- Deps: R0
- Stages: execute
- Status: done
- Lead: executor
- Accept: all existing tests green; `test_cli_help_unchanged`; `test_no_import_cycles: import
  every hive.* module in isolation -> ok`; `test_util_imports_nothing_from_hive`;
  `test_guard_is_standalone`; `test_driver_claude_matches_constants: get_driver("claude")
  .default_command -> today's string; queen_extras -> today's --tools list and
  --strict-mcp-config`; `test_system_key: system = "claude" accepted at all four levels, system =
  "x" -> exit 2 naming the known drivers`; `test_wheel_has_drivers` (wave 2 slice);
  `hive.cli:main` entrypoint unchanged. Validate: recipe in Scope Notes (behaviour identical).
- Artifacts: ->

### R2: Per-instance removal
- Goal: `hive stop TYPE --index N` and `hive stop <type>-<machine>-<N>` remove exactly those
  instances while others keep running (D6); done when stop of `-1` keeps `-2` across a reconcile.
- Owns: `hive/configedit.py`, `hive/reconcile.py`, `hive/workers.py`, `hive/config.py`,
  `hive/queen/CLAUDE.md`, `tests/test_configedit.py`, `tests/test_reconcile.py`,
  `tests/test_tmux.py`, `tests/test_cli.py`, `docs/commands.md`.
- Deps: R1a
- Stages: execute
- Status: done
- Lead: executor
- Accept: `set_indices: count=3 minus 1 -> indices=[2,3], count line removed, verify ok`;
  `set_indices_collapses: indices=[2,3] plus 1 -> count=3`; `parse_indices_and_count_exclusive ->
  exit 2`; `desired_panes_sparse: indices=[2,3] -> names -2, -3 only`;
  `plan_sparse_does_not_restart_hole`; `stop_by_index: stop a --index 1 with count 2 ->
  indices=[2], pane -1 killed, -2 alive`; `stop_by_name: stop a-t-1 -> same`;
  `stop_type_wins_over_instance_name: type a-t-1 exists and type a exists -> stop a-t-1 lowers
  type a-t-1's count; hint names --index`; `stop_mixed_targets_is_usage_error`;
  `stop_unknown_name -> exit 2 with hint`; `spawn_fills_lowest_free: indices=[2] spawn -n 1 ->
  count=2`; `list_shows_indices_when_sparse`; `adopt_sparse: legacy pane -1 with indices=[2] ->
  unmanaged, not adopted`; tmux lifecycle test for stop-by-index then reconcile. Validate:
  recipe; `reconcile` keeps the hole; `spawn -n 1` refills it.
- Artifacts: ->

### R1: Drivers for Claude Code, OpenCode v2 and Codex (gated)
- Goal: `system` selects a driver per agent, launcher and queen (D7, D15); done when a worker of
  each system starts in the test hive with correct unattended and trust handling.
  Codex and OpenCode both ship only if their external-device remote gates (G2, G1 in the child plan) pass; user decision 2026-10-27.
- Owns: `hive/drivers/*`, `hive/launch.py`, `hive/tmux.py` (`setup_pane` stores
  `@hive_session`), `hive/trust.py`, `hive/inspect.py`, `hive/config.example.toml`,
  `tests/test_drivers.py` (the `@hive_session` tests stub `tmux`), `tests/test_trust.py`,
  `tests/test_inspect.py`, `tests/test_args.py`, `docs/systems/claude.md`,
  `docs/systems/opencode.md`, `docs/systems/codex.md`, `hive/workers.py` (cmd_list, cmd_spawn,
  parse_env_args), `hive/configedit.py` (append_agent system), `hive/launchers.py`,
  `hive/config.py` (check_env, parse_queen, parse_agents default command), `tests/test_cli.py`,
  `tests/test_configedit.py`, `tests/test_config.py`.
- Deps: R1a, R2
- Stages: plan, execute
- Status: execute
- Lead: executor (child plan by planner first: the spike list of D15 and the per-driver launch
  templates verified against the local binaries)
- Accept: spike report first (fresh config dir launch per system in the test hive: dialogs seen,
  RC consent, Codex `-c` hook injection and hook trust, OpenCode `--standalone` plus
  `--version` probe, and on OpenCode v2 the status API: which endpoint a standalone pane
  exposes, the session identity it reports and the idle event name, since research A3 verified
  these on v1 only; R3's interface is fixed from that result), then: `system_precedence: agent > launcher > defaults > claude`;
  `claude_required_tokens: command without --remote-control -> exit 2 as today`;
  `codex_no_required_tokens`; `opencode_probe_v1 -> exit 2 naming the install command`;
  `session_id_placeholder: {session_id} expands to a fresh UUID per launch, stored as the tmux
  pane option @hive_session by setup_pane`; `resume_args_per_driver`; `hook_args_per_driver`; `list_prints_system`;
  `inspect_pattern_per_driver`. Validate: spawn one worker per system with `config_dir` (or the
  driver's config-dir equivalent) under the profile; `capture-pane` shows each tool's prompt;
  `list` shows `waiting=` for a blocking dialog; `down`.
- Artifacts: .supervisor/working/plans/plan-r1-drivers.md

### R5: Multi-node control over ssh
- Goal: `hive --node NAME <cmd>` proxies to a remote hive (D8) and a node runs queen-less
  (D5); done when the local test hive drives the swarm test hive.
- Owns: `hive/nodes.py`, `hive/config.py`, `hive/cli.py`, `hive/queen/hooks/guard.py`,
  `hive/queen/CLAUDE.md`, `tests/test_nodes.py`, `tests/test_guard.py`, `tests/test_config.py`,
  `docs/multi-node.md`.
- Deps: R0, R1a, R2
- Stages: execute
- Status: done
- Lead: executor
- Accept: `node_argv: node swarm profile test, [list] -> ssh -o BatchMode=yes -o
  ConnectTimeout=10 swarm -- '/home/u/.local/bin/hive --profile test list'` (shlex-quoted);
  `node_without_profile_refused_from_named_profile -> exit 2`;
  `node_default_profile_refused_from_named_profile: profile = "default" -> exit 2`;
  `node_attach_refused -> exit 2`; `node_exit_code_passthrough: fake ssh exits 3 -> 3`;
  `ssh_unreachable: fake ssh exits 255 -> exit 1, message names the node`;
  `nodes_list_output`; guard: `--node swarm list -> allow`, `--node swarm down -> ask`, `--node swarm --profile x list -> block`,
  `--node 'bad;name' list -> block`, `--profile x list -> block` (unchanged). Validate: D9 venv
  on swarm; `[[nodes]] name="swarm" host="swarm"
  hive="/home/sjoosten/dev/hive-queen/.venv/bin/hive" profile="test"` in the local test
  profile; `--node swarm spawn/up/list/stop/down`; swarm's production listing unchanged.
- Artifacts: ->

### R3: Done/idle detection
- Goal: `hive list` and `hive status` report a per-pane state from native events with a tmux
  fallback (D16); done when a worker of each system shows `done` after a turn and `blocked` on a
  permission prompt.
- Owns: `hive/hooks/*`, `hive/activity.py`, `hive/drivers/*` (hook fixes only),
  `hive/launch.py` (hook injection line), `hive/workers.py` (`cmd_list` state field),
  `hive/lifecycle.py` (`cmd_status` state), `pyproject.toml` (package data `hooks/*`),
  `tests/test_activity.py`, `tests/test_hooks.py`, `docs/idle-detection.md`,
  `hive/config.py` (state_dir in parse_config/lenient_config), `hive/tmux.py` (setup_pane status
  reset), `hive/queen/CLAUDE.md` (hive list bullet only), `tests/test_cli.py`,
  `tests/test_drivers.py`, `tests/test_args.py`, `tests/data/fake_worker.py`,
  `tests/test_driver_opencode.py`, `tests/test_driver_codex.py`.
- Deps: R1
- Stages: plan, execute
- Status: execute
- Lead: executor (child plan by planner: the status file schema, the per-event mapping per
  driver from research A3, the OpenCode poll)
- Accept: `status_hook_writes_file: Claude Stop JSON on stdin -> state done, session_id set`;
  `status_hook_notification_permission -> blocked`; `status_hook_codex_stop -> done`;
  `status_hook_session_end -> dead`; `pane_state_prefers_hook_file_over_tmux`;
  `tmux_fallback_quiet: stable hash 30 s, non-shell command -> quiet`;
  `tmux_fallback_dead: shell command -> dead`; `list_prints_state_source_age`;
  `status_prints_state`; `hook_args_passed_on_every_launch: resume command still contains the
  hook flags`. Validate: a Claude and an OpenCode worker in the test hive (`config_dir` under the
  profile): send a prompt via `send-keys`, `list` shows `busy` then `done`; a fake worker (D13)
  shows `quiet` via the fallback; `down`. executor validates with tests/data/fake_worker.py (Claude-shaped events through the real --settings injection) plus the D13 worker for the tmux fallback; real Claude/OpenCode/Codex checks are user-run, one Log line each.
- Artifacts: .supervisor/working/plans/plan-r3-done-detection.md

### R4: Resume sessions
- Goal: a stopped worker restarts into its previous session (D17); done when `spawn --resume`
  restores a worker whose session id was kept.
- Owns: `hive/sessions.py`, `hive/workers.py`, `tests/test_sessions.py`, `docs/resume.md`.
- Deps: R1, R3
- Stages: execute
- Status: done
- Lead: executor
- Accept: `record_and_load_roundtrip`; `stop_forgets_without_keep`; `stop_keep_session_records
  the id from the status file, else @hive_session`; `resume_without_hook_file_across_invocations:
  stop --keep-session in one process, spawn --resume in another, no status file -> command
  contains --resume <uuid>`; `resume_unknown_name -> exit 2`;
  `resume_args_at_args_placeholder: command contains driver.resume_args(id)`;
  `resume_keeps_hook_flags`; `state_file_under_profile_dir`. Validate: Claude worker in the test
  hive, `stop TYPE --index 1 --keep-session`, `spawn TYPE --resume <name>`, capture-pane shows
  the previous conversation; `down`.
- Artifacts: ->

### R6: Queen on every supported system
- Goal: the queen pane runs on each driver with equivalent instructions and command guard
  (D18); done when the OpenCode and Codex spikes pass and both queens pass the guard checks, or
  the package returns blocked with Q2.
- Owns: `hive/queen/*`, `hive/queen.py`, `hive/drivers/codex.py`, `hive/drivers/opencode.py`
  (`supports_queen`, `queen_extras`), `pyproject.toml` (package data), `tests/test_guard.py`,
  `tests/test_queen.py`, `docs/queen.md`, `hive/drivers/claude.py` (queen_files),
  `tests/test_guard_opencode.py`, `tests/test_guard_codex.py`, pointer edits in `tests/test_cli.py`
  (two materialize tests move to tests/test_queen.py) and `tests/test_split.py`.
- Deps: R1, R3, R5
- Stages: plan, execute
- Status: execute
- Lead: executor (child plan by planner: the spike protocol of D18 first)
- Accept: spike first (Codex queen: allow `hive list`, deny `hive list; ls`, deny every Claude
  `ask` command; outcome recorded in the child plan's Log), then: `guard_core` tests pass for
  every system shim with the inputs of today's `tests/test_guard.py`;
  `materialize_queen_per_system: [queen] system=opencode -> AGENTS.md and opencode.json written,
  claude files absent`; `queen_system_unsupported -> exit 2 while supports_queen is false`;
  `queen_extras_per_system`. Validate: one real queen per supported system in the test hive with
  its config dir under the profile, `hive list` allowed, `hive list; ls` blocked, torn down in
  the same session.
- Artifacts: .supervisor/working/plans/plan-r6-queen-systems.md
- Landing: up to three squashes: Slices 1-3 after R4 lands; unit O after R1 Slice 5; unit C after R1 Slice 6 and R3 Slice 4.

### R8b: Docs polish for new users
- Goal: README and every `docs/` page read as one coherent set with the 2.0 features and the
  `hive queen` name; done when no stub remains and the getting-started path is complete.
- Owns: `README.md`, `docs/**`, `tests/test_docs_links.py`.
- Deps: R1, R2, R3, R4, R5, R6
- Stages: write
- Status: write
- Lead: writer
- Accept: no stub lines; link check passes with no allowed-absent pages except
  `docs/upgrade.md` (R7); per-system pages state the versions observed and the Codex
  limitations (no remote access, `/rename`, queen status). Validate: none (docs only).
- Artifacts: ->

### R7: Release 2.0 and rename
- Goal: `main` carries `VERSION` 2.0 tagged `v2.0`, dist `hive-queen`, repo `hive-queen`,
  upgrade note; done when `## Verification` passes.
- Owns: `pyproject.toml`, `uv.lock`, `VERSION`, `hive/util.py` (`get_version`),
  `docs/upgrade.md`, `docs/development.md` (release procedure), URL lines in `README.md` and
  `docs/`.
- Deps: R8b
- Stages: execute
- Status: execute
- Lead: executor
- Accept: `uv run hive --version -> hive 2.0`; `uv build` produces `hive_queen-2.0*`;
  `test_package_name: pyproject name hive-queen, scripts hive = hive.cli:main, get_version
  queries hive-queen`; installed into a scratch `UV_TOOL_DIR` from a directory without
  `VERSION`, `hive --version -> hive 2.0`; `git tag` lists `v2.0` on the release commit;
  `docs/upgrade.md` covers `uv tool uninstall hive && uv tool install
  git+https://github.com/sly2j/hive-queen`, `hive restart` to re-sync queen files, the unchanged
  config path; the release commit uses `--no-verify` (D12), documented. Steps: `gh repo rename
  hive-queen`, `git remote set-url origin`, push `main` and the tag (the user confirms once
  before the tag and push, per the landing policy). Validate: `## Verification`; no live hive
  command outside the test profile.
- Artifacts: ->

## Open Questions

- Q1: Publish `hive-queen` to PyPI at 2.0, or git-URL installs only? Recommended: git URL only
  for 2.0 (no account or token work in this release); PyPI as a roadmap item.
- Q2 (asked only if an R6 spike fails): ship 2.0 with that system worker-only and the queen
  limitation documented, or hold the release until the guard port works? Recommended: ship
  worker-only with the limitation documented and a roadmap item, since the user's remote-access
  rule already makes Codex a worker without remote access.

## Log

- 2026-10-27 decision: split hive/cli.py into modules and a driver seam first (R1a), behaviour preserving, tests re-pointed to owning modules; source: lead
- 2026-10-27 decision: test profile is `hive --profile NAME` / `HIVE_PROFILE`, dir `<config_home>/hive/profiles/<name>/`, defaults prefix `<name>`, session `<name>-agents`, socket `hive-<name>`; source: lead
- 2026-10-27 decision: a named profile refuses the default profile's socket in both strict and lenient parsing, uses unit `hive-<name>.service`, exports HIVE_PROFILE in its panes; source: lead
- 2026-10-27 decision: `[queen] enabled = false` added in R0; empty hive `up` exits 0 with a message and no session; the session starts from the first desired pane; source: lead
- 2026-10-27 decision: per-instance removal via `indices` exclusive with `count`, collapsing to `count` when contiguous; `stop` target rule: type wins, `--index` is the unambiguous form; supersedes the "never stored" line of 2026-10-22-instance-naming-and-queen-rename.md in spirit (N still derived); source: lead
- 2026-10-27 decision: `system` key at four levels, default claude; drivers in hive/drivers/; R1a accepts only claude; source: lead
- 2026-10-27 decision: nodes are `[[nodes]]` (listed by `hive nodes`); `hive --node` proxies over ssh BatchMode; from a named local profile the node must name a non-default remote profile; 255 maps to exit 1; attach refused; source: lead
- 2026-10-27 decision: swarm dev build at /home/sjoosten/dev/hive-queen/.venv, test profile only; source: lead
- 2026-10-27 decision: per-pane status files and sessions.json live under `<profile dir>/state/`; config.toml stays the only desired state; source: lead
- 2026-10-27 decision: feature packages own one docs page each and never README.md; R8a skeleton first, R8b polish before R7; source: lead
- 2026-10-27 decision: dist hive-queen, import package hive, packages list gains hive.drivers, get_version queries hive-queen, release commit with --no-verify, tag v2.0, gh repo rename; source: lead
- 2026-10-27 decision: Claude is the reference driver (session ids assigned by hive, hooks via --settings re-passed on every launch); OpenCode targets v2.0.x with a version probe and --standalone; Codex ships as a worker without remote access, hooks via -c with hook-trust bypass, resume by id, /rename documented; pi to the roadmap; source: lead, from research 2026-10-27
- 2026-10-27 decision: done detection is native events to a status file, tmux fallback reports only busy/quiet/dead; source: lead
- 2026-10-27 decision: resume via `stop --keep-session` and `spawn --resume NAME`; source: lead
- 2026-10-27 decision: queen per system under hive/queen/<system>/ with shared guard_core; OpenCode guard uses the v2 permission schema; Codex and OpenCode queens only after a spike, a failed spike returns Q2 to the user; source: lead
- 2026-10-27 decision: the launch session id lives in the tmux pane option @hive_session; sessions.json records it only on stop --keep-session; source: lead
- 2026-10-27 decision: wave order R0+R8a, R1a (R8a may overlap), R2+R1, R5+R3, R4+R6, R8b, R7 with disjoint Owns per wave; source: lead
- 2026-10-27 decision: no `shell` driver and no `hive nodes add`: the fake worker command covers test hives, nodes are hand-edited in config.toml (scope-critic S7, S8); source: lead
- 2026-10-27 R8a: done; README 72 lines, 10 docs/ pages, tests/test_docs_links.py green, landed on main as 23f87a0 (squash); deferred: docs/commands.md and docs/queen.md created with today's content against the letter of D11 (supervisor confirmed keep), placeholder pages for unshipped features not created (plan does not require them)
- 2026-10-27 R0: done on feat/r0-test-profile, landed on main as c5f8de6 (squash), pytest 413 passed, test-hive recipe passed here and on swarm (D9 dev clone at /home/sjoosten/dev/hive-queen); deferred: C3 legacy-queen stop rejected as legacy-only; leftovers kept for reuse: ~/.config/hive/profiles/test/ on both machines
- 2026-10-27 decision: docs/commands.md and docs/queen.md exist from R8a with today's content; R2 and R6 edit those pages rather than create them (supervisor; relaxes the letter of D11)
- 2026-10-27 decision: no PyPI publication at 2.0, git-URL installs only; PyPI goes to the roadmap (supervisor default answering Q1; user did not object)
- 2026-10-27 decision: if an R6 queen-port spike fails for a system, that system ships worker-only with the limitation documented; the release is not held (supervisor default answering Q2; user did not object)
- 2026-10-27 note: `gh` is not installed on this machine; R7's `gh repo rename` needs gh installed or a manual rename in the GitHub UI; CI results are not checkable from the shell
- 2026-10-27 decision: user: a system ships in this release only if a user on another device can reach its sessions without tunnel-building ("the entire point of hive queen is to make remote sessions available on other devices"); Codex is deferred to the roadmap until it offers remote control on Linux; OpenCode v2 is the approved generation and ships only if the R1 spike proves external-device remote access without tunnels; otherwise R1 reduces to the Claude reference driver on the driver seam and R6/R8b shrink accordingly
- 2026-10-27 decision: user: OpenCode service-password exposure deferred (machine is secure), no action
- 2026-10-27 R1a: done; cli.py split into 11 modules plus hive/drivers (claude driver, `system` key at four levels, claude only), cli.py 112 lines, 422 tests green on 3.11/3.12/3.13, test-profile recipe identical to main and production panes unchanged; landed on main as 78e5215 (squash); deviations from the plan's module map accepted by critic (ConfigError in util; edit_config/check_config_writable/expand_config_dir in config; expand_pane in launch; depth_int in roots; BROKEN_CONFIG_NOTE in lifecycle; golden help per Python version); deferred to R1: spawn copying a launcher's `system` (no agent-launcher link), Claude-specific preflight/env texts
- 2026-10-27 R2: done; `[[agents]] indices` (exclusive with count), `hive stop TYPE --index N` / `hive stop NAME...`, spawn fills lowest free indices, list shows `indices=` when sparse; pytest 454 passed; test-profile out-of-order stop/refill validated, production panes unchanged; landed on main as 24f2b4f (squash); deviation: agent_indices lives in reconcile.py (import cycle); deferred: docs/configuration.md indices row (R8b), config.example.toml indices mention (R1), multi-line indices array editing (rejected, safe-failing), memory entry 2026-10-22-instance-naming-and-queen-rename partly superseded by D6 (curator at close-out)
- 2026-10-27 R1 (planner): child plan written at .supervisor/working/plans/plan-r1-drivers.md, spikes run for Claude, OpenCode and Codex, gates G1 (OpenCode, docs pass) and G2 (Codex, daemon pass) await user live tests; deferred: OpenCode phone test and Codex app confirmation to the user (Slice 3); Claude RC-consent and resume+RC reattach untested (R4)
- 2026-10-27 amend D15: Codex back in this release under gate G2 (user showed `codex remote-control` + pair working on swarm, 2026-10-27; research claim "Linux not a listed host" superseded; roadmap R9 returns to R1 pending G2); OpenCode = shared service + API-created session + `--auto` + `pair --remote`, `min_version` from G1, `--standalone` dropped; Codex = default CODEX_HOME, daemon ensured at launch, `-c` hooks + `--dangerously-bypass-hook-trust`, SessionStart session id, trust in config.toml, `/rename` documented not automated
- 2026-10-27 amend D16 (R3 interface): OpenCode poll `GET /api/session/active` + SSE `/api/event` (basic auth `opencode:<password>`; no `/session/status`); Codex hooks SessionStart/Stop/SessionEnd/PermissionRequest via `-c`; Codex `notify` rejected as done signal
- 2026-10-27 amend D18 (R6): OpenCode v2 key is `permissions` (plural, `{action,resource,effect}`); OpenCode queen must attach to the shared service; Codex queen runs in the default CODEX_HOME; Codex queen spike restored
- 2026-10-27 risk: a Codex daemon started by `hive up` under systemd dies with the hive service; `up` re-ensures it
- 2026-10-27 R1 (supervisor): Slices 1, 2, 4 dispatched to executor on feat/r1-claude-driver; Slices 5 (OpenCode) and 6 (Codex) blocked on user gate tests G1/G2
- 2026-10-27 R5: done; `[[nodes]]` (name, host, hive, profile, description), global `hive --node NAME <cmd>` over `ssh -o BatchMode=yes` with exit passthrough, refuses attach/option injection/default-profile nodes from a named local profile, `hive nodes`, guard allows `--node NAME`, docs/multi-node.md; 506 tests green; local test profile drove the queen-less swarm test profile live, production panes unchanged on both machines; landed on main as b5136c0 (squash); lead decisions: `--node NAME` ends local option parsing, no `--profile` sent for default remote profile (older remote hives work); deferred: `hive nodes`/`--node` in docs/commands.md (R8b); note for R6: keep the guard's `--node` shift in guard_core; swarm dev clone is on feat/r5-nodes, check out main there after the next bundle
- 2026-10-27 R1 (slices 1, 2, 4): done; claude driver session ids (@hive_session, --session-id appended or {session_id}), hook/resume args, waiting kinds, system=/waiting=<kind> in list, --system on spawn/launchers add/inspect-launcher, driver default command, version probe with min_version, KNOWN_SYSTEMS texts, every driver's config_dir_env rejected; pytest 559 passed both commands; live spike-r1 check: real claude waiting=theme, @hive_session equals the process --session-id, production panes and ~/.claude.json unchanged; landed on main as 4a5e670 (squash); deviations: driver `binary` attribute for the probe, --system skips the default launcher, the queen system check applies only when the queen is enabled; deferred: slices 3/7 (user gates), 5/6 (wait on gates), guard.py --system handling (R6); upgrade note for R7: configs whose command lacks {session_id} get --session-id appended after upgrade
- 2026-10-27 R3 (planner): child plan written at .supervisor/working/plans/plan-r3-done-detection.md (Slice 1 Claude path + fake worker, Slice 2 docs/queen bullet, gated Slices 3 OpenCode poll and 4 Codex hooks); critic codex round 1 REVISE, round 2 PASS; deferred: real-agent smokes (Slices 2-4) and the token round Q1 to the user
- 2026-10-27 amend D16: `source` values hook|api|tmux; Claude hooks also UserPromptSubmit and StopFailure, Notification matcher adds agent_needs_input; SessionStart maps to done; status and screen files reset at launch; OpenCode by one-shot poll only (no SSE in R3)
- 2026-10-27 amend D17: the OpenCode session id comes from `@hive_session` (R1 D-R1.6), not the status file; Codex from the status file unchanged
- 2026-10-27 R3 (supervisor): Slices 1-2 dispatched to executor on feat/r3-done-detection; Slices 3-4 blocked on gates G1/G2
- 2026-10-27 R3 (slices 1, 2): done; status hook + activity.py + --settings injection of 6 Claude events + state=/source=/age= in list and status + fake worker + docs/idle-detection.md + queen bullet; pytest 602 passed both commands; test-profile fake-worker sequence done/busy/done/blocked/quiet/dead passed, production panes unchanged; landed on main as e09c535 (squash); deferred: slices 3/4 (gated on R1 G1/G2), real-Claude --settings smoke moved to R4 step 0, Q1 token round (user-run), C1 single list-panes call (plan prescribes the extra call; optional RunningPane fields fix)
- 2026-10-27 R6 (planner): child plan written at .supervisor/working/plans/plan-r6-queen-systems.md (Slices 1-3 ungated: guard_core + per-system layout, `--system` guard rule, Claude live check; units O OpenCode and C Codex gated on R1 Slices 5/6 with spike-first protocol D-R6.10); critic codex round 1 REVISE, round 2 PASS; decision: `hive spawn --system X` asks unless X is already a system in config.toml; Codex queen denies every Claude `ask` case with a run-by-hand message, rules-based prompts to roadmap; deferred: live checks to executor/user through the test profile, Codex spike needs the user's go-ahead (default CODEX_HOME)
- 2026-10-27 roadmap candidate (from R6): Codex rules-based prompts (`-a on-request` + `.codex/rules`) replacing the Codex queen's deny-with-message (D-R6.11); curator adds at close-out
- 2026-10-27 R6 (supervisor): execution of Slices 1-3 held until R4 lands (both edit the queen instruction file; the guard rule needs R4's final flag names)
- 2026-10-27 decision: opencode gate fail (G1: `opencode pair --remote` relay did not work; user hypothesis: blocked on the work network); OpenCode deferred to the roadmap for this release; R1 Slice 5, R3 Slice 3 and R6 unit O dropped; source: user
- 2026-10-27 decision: codex gate pass (G2: hive-launched codex pane on swarm visible and drivable from the paired app); pairing persisted across a daemon restart, only `codex remote-control start` was needed, no re-pair; `start` idempotency on a running daemon unverified, so hive checks for a running daemon before starting one; source: user
- 2026-10-27 R1 (supervisor): Slice 6 (Codex driver) dispatched to executor on feat/r1-codex-driver; R3 Slice 4 and R6 unit C follow once it lands
- 2026-10-27 R4: done; stop --keep-session records session ids (status file or @hive_session) in <profile>/state/sessions.json, spawn TYPE --resume NAME relaunches with the driver's resume args (--resume <id> for Claude; --session-id dropped since Claude rejects both), hooks carried, list shows kept sessions, hive/sessions.py, docs/resume.md; Step 0 real-Claude --settings smoke passed (all 6 hook events accepted); live resume verified with fake worker and real Claude at theme; pytest 620 passed; landed on main as a3b3ead (squash); deferred: user check of a resumed conversation in a logged-in config dir; guard --resume/--keep-session handling to R6 slice 2; docs/systems/claude.md resume line to R8b
- 2026-10-27 R6 (supervisor): Slices 1-3 dispatched to executor on feat/r6-queen-core after R4 landed
- 2026-10-27 R6 (slices 1-3): done; shared hive/queen/guard_core.py (Verdict API, reason strings byte-identical), per-system layout hive/queen/{queen.md,claude/{rules.md,settings.json,hooks/guard.py}}, composed CLAUDE.md, RENDERERS, guard_core copied to .claude/hooks, spawn --system asks unless configured, --system/--resume value options, stop --keep-session prompt-free; pytest 639 passed both commands; live: test-profile Claude queen reached waiting=theme with composed CLAUDE.md and hooks, materialized guard allow/deny/ask checked, production panes and ~/.config/hive/queen, ~/.claude.json mtimes unchanged; landed on main as 4c46d35 (squash); deferred: unit O (G1), unit C (after R1 Slice 6), interactive queen prompt check (needs login)

## Todo

- [ ] R0 test profile landed on main
- [ ] R8a docs skeleton landed on main
- [ ] R1a cli split landed on main
- [ ] R2 per-instance removal landed
- [ ] R1 child plan written, spike run, drivers landed
- [ ] R5 multi-node landed, swarm test hive validated
- [ ] R3 child plan written, done detection landed
- [x] R4 resume landed
- [ ] R6 child plan written, spikes passed (or blocked with Q2 answered), queen per system landed
- [ ] R8b docs polish landed
- [ ] R7 release: VERSION 2.0, tag v2.0, rename, upgrade note, push (user confirms tag and push)
- [ ] Verification section passes; production hives unchanged on both machines
