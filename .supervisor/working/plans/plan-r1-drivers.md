# Plan: R1 drivers (Claude reference; OpenCode v2 and Codex behind a remote-access gate)

Child plan of `.supervisor/working/plans/plan-hive-queen-2.0.md`, package R1, release `2.x`.
Planned 2026-10-27 against `main` 78e5215 (R1a landed) and D7/D15. Research:
`.supervisor/working/research/2026-10-27-hive-queen-2.0-systems.md` (cited "research, section");
its "Codex remote control: Linux not listed" is superseded: the user paired swarm's Codex daemon
with the macOS app on 2026-10-27. Spike results of 2026-10-27 are in `## Decisions`. Gate rule
(memory `.supervisor/memory/decisions/2026-10-27-ship-only-systems-with-tunnel-free-remote.md`):
a system ships only if a user on another device reaches its sessions without tunnels.

## Goal

The `system` key of R1a selects a complete driver per agent, launcher and queen. The `claude`
driver gains everything R3 (done detection) and R4 (resume) read: a hive-assigned session id,
`hook_args`, `resume_args`, dialog detection, `system=` in `hive list`. An `opencode` driver and a
`codex` driver ship only if their live gate (Slice 3, user-run) passes: OpenCode workers attach to
the shared `opencode service` reached by `opencode pair --remote`; Codex workers attach to the
per-machine `codex` daemon paired once with the ChatGPT or Codex app.

Non-goals: pi (roadmap R10); hook injection into launches and the status file (R3); `stop
--keep-session` and `spawn --resume` (R4); OpenCode and Codex queens (R6; `supports_queen =
False` here); new `hive` subcommands for pairing (one-time user steps, documented); OpenCode v1;
automating `/rename` for Codex (titles come from the first prompt; documented).

Expected change size: Slices 1-2 (Claude) about 300 lines added and 40 removed; Slice 4 (seam
plumbing) about 200 added; Slices 5-6 about 350 added per shipped driver with tests and its docs
page; Slice 7 about 80 lines of example config. Total up to 1300 added, 60 removed. This plan
stays under 400 lines.

## Approach

1. Finish the `claude` driver first and alone (Slices 1-2): every protocol method the parent's
   `Driver` shape lists, checked in the test hive with a real `claude` in a fresh config dir,
   which stops at the theme screen and costs no tokens. R3 and R4 need only this.
2. Gates (Slice 3) are user actions: exposing a service to the internet or confirming an app view
   is not something an agent does (the harness refused the first attempt, rightly). Each gate
   writes one `## Log` decision line; a failed gate sends that system to the roadmap.
3. Seam plumbing (Slice 4) lands once for every future system: `spawn --system`, `launchers add
   --system`, `inspect-launcher --system` (today `cmd_spawn`, `launchers_add` and
   `cmd_inspect_launcher` use `cfg["system"]`, so a launcher's system never reaches the new
   agent: `hive/workers.py:147,158,212`, `hive/launchers.py:91,162`), the driver-default command
   for a non-default system, version probe with `min_version`, generalised `config_dir_env`
   rejection. No driver stubs: each gated driver lands complete in its own slice.
4. R2 is executing in `hive/workers.py`, `hive/config.py` and `hive/reconcile.py` now. Slice 1
   touches none of them and may run concurrently; Slices 2-7 start after R2 lands (rebase).
5. OpenCode: workers attach to the shared service (no `--standalone`), hive creates the session
   through the service API before launch and opens it with `-s <id>`, so the id is known at launch
   like Claude's. Rejected: `--standalone` per pane (D15): a private server is invisible to `pair`
   and the web UI (spike; https://opencode.ai/v2/docs/cli). Rejected: discovering the id from
   the db (the `session_v2` row appears only after the first message; two workers in one dir are
   ambiguous); kept as the fallback if `POST /api/session` cannot take a directory.
6. Codex: workers run in the user's default `CODEX_HOME` (the daemon is per `CODEX_HOME`; only the
   default one is paired), hive ensures the daemon runs before a Codex pane starts, the session
   id comes from the `SessionStart` hook (R3), trust is seeded in `$CODEX_HOME/config.toml`.
   Rejected: `-c projects.<dir>.trust_level` (does not suppress the folder prompt, spike);
   `notify` as the done signal (fires for the internal title-generation call too).

## Decisions

Gate results (docs and local spikes, 2026-10-27; the live confirmations are Slice 3):

- G1 OpenCode: `opencode pair --remote` is a blind TLS relay through OpenTunnel
  (`*.opentunnel.xyz`, run by the OpenCode org; https://opencode.ai/v2/docs/cli/web,
  github.com/anomalyco/opentunnel): no port forwarding, any network, access by single-use
  5-minute link plus the server password; the first use asks for confirmation (`--yes` for
  scripts). Equivalent in user effort to Claude's `--remote-control`: docs-level pass. Local
  2.0.14 has no `--remote` flag (`pair --help` shows only `--url`); v2.2.0 (2026-10-27) is the
  first candidate. Clients: browser or the OpenCode app (QR). Swarm runs 2.0.12.
- G2 Codex: a `codex` TUI launched by hive in a `--profile test` pane on swarm registered on the
  paired shared daemon (`codex agents` listed it; thread row in `~/.codex/state_5.sqlite` with
  originator "Codex Desktop"): pass pending the user's app-side confirmation. Pairing state is
  on disk (`remote_control_enrollments`, one row for `swarm`), so it is expected to survive a
  daemon restart and reboot; the `enabled` flag is not persisted, so `codex remote-control
  start` is likely needed after a restart, without re-pairing (inference; docs: signing out
  "doesn't remove your existing device pairings"). No autostart exists (no unit, no crontab).
  There is no `remote-control status` subcommand. Clients: ChatGPT mobile apps, Codex desktop.

Driver decisions:

- D-R1.1 Session id: `setup_pane` (the path every pane takes, `hive/tmux.py:91`; `cmd_up` calls
  it directly for the first pane, `hive/lifecycle.py:118`) calls `session_id =
  driver.prepare_launch(env, pane) or uuid4()`, expands the command with it and stores it as pane
  option `@hive_session` when `driver.assigns_session_id`. `expand_pane(cfg, pane,
  session_id=None)` expands `{session_id}` and, when the command lacks the placeholder, appends
  `driver.session_args(id)` (same rule as `{args}`); with `session_id=None` (the lifecycle print
  lines `:78,:120`) it appends nothing and leaves the placeholder. Claude: `prepare_launch`
  returns `None` (hive's uuid is used), `session_args = ["--session-id", id]` (`--session-id
  <uuid>` "must be a valid UUID", `claude --help`), default command gains ` --session-id
  {session_id}` (D15). OpenCode: `prepare_launch` returns the API-created id (D-R1.6). Codex:
  `assigns_session_id = False`, `session_args = []`; R3's `SessionStart` hook delivers
  `session_id` before the first prompt (spike JSON), R4 reads the status file (D17). A wrapper
  command (`sh -c '...'`) must carry `{session_id}` inside the quotes: an appended flag becomes
  the wrapper's `$0`.
- D-R1.2 Dialog detection: `driver.waiting_kind(screen) -> str | None` over `waiting_kinds:
  ((kind, phrases), ...)`; `cmd_list` prints `waiting=<kind>`. `looks_like_prompt` stays on
  `ClaudeDriver` as a wrapper (`waiting_kind(screen) == "trust"`) through Slice 1, because
  `hive/workers.py:48` calls it and `tests/test_cli.py:613` exercises it; Slice 2 removes it with
  the `cmd_list` change. Claude (spike screens): `trust` ("i trust this folder", "trust the files
  in this folder"), `theme` ("choose the text style"), `login` ("select login method"),
  `rc_consent` ("enable remote control", from the RC docs, unverified live); a fresh config dir
  shows theme, then login (verified); trust and RC consent come after login. Codex: `trust`
  ("trust this folder?"), `hooks_review` ("hooks need review"), `login` ("sign in", unverified:
  fresh `CODEX_HOME` untested). OpenCode: none (fresh XDG dirs start at the prompt on the
  built-in free model, verified). Docs: attach once per config dir.
- D-R1.3 Hooks: Claude `hook_args(hook_cmd, state_file) = ["--settings", <inline JSON>]` with
  command hooks on `SessionStart`, `Stop`, `Notification` (matcher
  `permission_prompt|idle_prompt`) and `SessionEnd` (shape verified in the hooks docs; inline JSON
  accepted, cli-reference); `resume_args = ["--resume", id]`. Codex `hook_args` = `-c
  'hooks.SessionStart=[{hooks=[{type="command",command="..."}]}]'`, same for `Stop`, `SessionEnd`,
  `PermissionRequest` (-> `blocked`), plus `--dangerously-bypass-hook-trust` (without it a
  "Hooks need review" screen blocks the pane and hooks do not run; verified); `resume_args =
  ["resume", id]`, placed at `{args}`, so the default Codex command is `codex {args} -a never -s
  workspace-write` (whether `resume` accepts `-a`/`-s` is R4's spike). OpenCode `hook_args = []`
  (R3 polls the API, D-R1.8); `session_args = resume_args = ["-s", id]`.
- D-R1.4 `system=` in `hive list`: queen line, each agent line and each pane line gain
  `system=<name>`; `Pane.system` exists (`hive/reconcile.py:24`) and the type-to-system map at
  `hive/workers.py:44`, so no new lookup is needed.
- D-R1.5 Version probe: `driver.probe(binary)` runs `<binary> --version`, parses
  `v?(\d+)\.(\d+)\.(\d+)`, returns the string or `None`. `cmd_spawn` for a new type exits 2 when
  the probe is below `driver.min_version`, naming `driver.install_hint`; `preflight` only warns.
  Claude `2.1.311 (Claude Code)`, `min_version = None`. OpenCode `opencode vX.Y.Z` (verified
  2.0.14 and 2.0.12), `min_version` = the version G1 passes on (2.2.0 expected), hint `curl -fsSL
  https://opencode.ai/v2/install | bash`. Codex `codex-cli 0.164.0`, `min_version = (0, 164, 0)`,
  hint `npm install -g @openai/codex`.
- D-R1.6 OpenCode launch (gated): default command `opencode --auto -s {session_id} {dir}` (TUI
  flags verified: `--auto`, `-s`, `--standalone`, `--server`, `--prompt`, `[<directory>]`; `-s`
  with an unknown id is silently ignored, so the session must exist first). `prepare_launch`
  calls `ensure_service(env)` (`opencode service start` under the pane env) then `POST
  /api/session` and `PATCH /api/session/{id} {"title": pane.name}` (both verified on a private
  server) and returns the id. `required_tokens = ()`, `required_placeholders = ()`,
  `unattended_args = ["--auto"]`, `instructions_file = "AGENTS.md"`, `supports_queen = False`,
  `queen_files = {}`, `trust_state` always trusted, `config_dir` on an opencode entry is a config
  error ("opencode isolates through XDG_* in env"), `env_scrub = frozenset()`, `inspect_pattern
  = OPENCODE_|XDG_|opencode|exec |env |export |HOME=`.
- D-R1.7 OpenCode service access: port from `$XDG_STATE_HOME/opencode/service.json` (default
  `~/.local/state`, port 49374), password from `$XDG_CONFIG_HOME/opencode/service.json`, HTTP
  Basic user `opencode` with an explicit `Authorization` header (verified). Paths resolve through
  the pane env, so a profile whose `[env]` sets the four `XDG_*_HOME` under the profile dir gets
  its own service, db and password (XDG relocation verified; one service per state file,
  inferred). Default profile: the user's own shared service; one `pair --remote` covers hive
  workers and the user's sessions. The service caches config at start; env changes need
  `opencode service restart` (observed).
- D-R1.8 R3 interface for OpenCode: `GET /api/session/active` -> `{data:{<id>:{type:"running"}}}`
  (`{}` when idle); `GET /api/session/{id}` has `outcome` and `time.idle`; SSE `GET /api/event`
  (`session.idle`, `session.execution.*`, `permission.asked` exist as strings in the binary,
  unverified live); `GET /api/permission/request` lists pending permissions. No
  `/session/status` on v2; everything is under `/api/*`.
- D-R1.9 Codex launch (gated): default command above; `unattended_args = ["-a", "never", "-s",
  "workspace-write"]`; `required_tokens = ()`, `required_placeholders = ()`; `config_dir_env =
  "CODEX_HOME"` (rejected in `env` like `CLAUDE_CONFIG_DIR`; the command sets it, for example
  `sh -c 'CODEX_HOME=<dir> exec codex ...'`; default none, because only the default `CODEX_HOME`
  reaches the paired daemon); `trust_state` reads `$CODEX_HOME/config.toml`
  `projects."<root>".trust_level == "trusted"`; `seed_trust` appends `[projects."<root>"]
  trust_level = "trusted"` when the table is absent and re-reads with `tomllib` (pattern
  `hive/configedit.py` `verify`); when the table exists with another value it refuses, naming the
  file (no in-place TOML edit). Non-git dirs show no prompt (verified), git dirs do, and whether
  the file entry suppresses it is the Slice 6 spike step (fallback: `waiting=trust`, docs say
  attach once). `instructions_file = "AGENTS.md"`, `supports_queen = False`, `queen_files = {}`,
  `inspect_pattern = CODEX_HOME|codex|exec |env |export |HOME=`, `versions = ("0.164.0",)`.
- D-R1.10 Codex daemon: `prepare_launch` for a pane with `config_dir` unset calls
  `ensure_daemon()` once per hive process: alive when `~/.codex/app-server-daemon/daemon.pid`
  (JSON `pid`) names a live process, else run `codex remote-control start` (the TUI would start a
  plain daemon anyway; `start` enables remote control for the already paired machine). A pane
  with its own `config_dir` gets no daemon handling (not remote-reachable by design; documented).
  Never `pair`, never `stop`; pairing is the user's one-time `codex remote-control pair`
  (documented, codes never typed by hive). A live daemon may run without remote control (the
  user's own TUI starts a plain one) and hive cannot tell (no `status`): if Slice 3 shows `start`
  is idempotent on a running daemon, `ensure_daemon` always runs `start` once per process and the
  pid check goes; otherwise the pid check stays and docs say to run `codex remote-control start`
  after a reboot. Under `hive.service` the daemon lands in the unit's cgroup and dies with it;
  `hive up` re-ensures it.
- D-R1.11 Codex names: no launch flag; the app shows the first prompt as title; hive sets the
  tmux pane title and documents `/rename`. Rejected: typing `/rename` by `send-keys` (TUI not
  ready for about 12 s after start, spike).
- D-R1.12 Driver registry and commands: `DRIVERS` (`hive/drivers/__init__.py:25`) stays an
  eager dict (`hive/tmux.py:13` builds `SESSION_ENV` from it); each gated driver slice adds its
  module and its one `DRIVERS` line. `KNOWN_SYSTEMS = ("claude", "opencode", "codex")` gives
  `get_driver` two texts: an unknown name lists `DRIVERS`, a known unregistered name says "not in
  this release". `parse_queen` (`hive/config.py:313`) exits 2 when the queen's driver has
  `supports_queen = False`. Command selection: an agent entry whose `system` differs from
  `[defaults] system` and has no `command` gets `driver.default_command` in `parse_agents`
  (`hive/config.py:370`, today only `parse_queen:319` falls back to the driver); `cmd_spawn
  --system X` without `--command` writes that default into the new entry explicitly. Rejected:
  lazy import by module name (breaks the `SESSION_ENV` union); skeleton driver modules.
- D-R1.13 Generalised Claude-only text: `check_launcher_command` (`hive/launch.py:47`) requires
  `driver.required_placeholders` (claude `("{name}",)`, others `()`) plus `required_tokens`;
  `preflight` (`:64`) and `warn_untrusted` (`:53`) name `driver.name` instead of "Claude";
  `check_env` (`hive/config.py:155-163`) and `parse_env_args` (`hive/workers.py:83`) reject every
  driver's `config_dir_env` (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`) with that driver's message;
  `inspect-launcher --system NAME` (default `[defaults] system`) picks `driver.inspect_pattern`
  (`hive/launchers.py:162,183`: the command takes a raw command string, so the system cannot be
  inferred).

## Outline

Pointers are into `main` 78e5215; signatures are the contract with R3/R4.

- `hive/drivers/__init__.py:9-22` `Driver` protocol gains `assigns_session_id: bool`,
  `min_version: tuple[int, ...] | None`, `install_hint: str`, `versions: tuple[str, ...]`,
  `required_placeholders`, `waiting_kinds`, `waiting_kind(screen) -> str | None`,
  `probe(binary) -> str | None`, `session_args(id)`, `resume_args(id)`, `hook_args(hook_cmd,
  state_file)`, `prepare_launch(env, pane) -> str | None`; `KNOWN_SYSTEMS`, `get_driver` texts
  (D-R1.12). `ValueError` stays the error type (`hive/config.py:132` `check_system` turns it
  into exit 2).
- `hive/drivers/claude.py:29-63` `ClaudeDriver`: `session_args`, `resume_args`, `hook_args`
  (D-R1.3), `waiting_kinds` (D-R1.2), `probe`, `versions = ("2.1.311",)`, `default_command`
  (`:8` `DEFAULT_QUEEN_COMMAND`) with `--session-id {session_id}`; `INSPECT_RE` `:25` stays.
- `hive/drivers/opencode.py` (Slice 5, gated): fields of D-R1.6; `service_paths(env) -> (url,
  password)`, `ensure_service(env)`, `create_session(env, directory, title) -> str` via
  `urllib.request` (dependencies stay `[]`).
- `hive/drivers/codex.py` (Slice 6, gated): fields of D-R1.9; `ensure_daemon()`, `trust_state`,
  `seed_trust` (TOML append or refuse), `hook_args` building `-c` values (D-R1.3).
- `hive/launch.py:42` `expand_pane(cfg, pane, session_id=None)` (D-R1.1); `:47`
  `check_launcher_command(command, where, system)` per D-R1.13; `:53` `warn_untrusted` and `:64`
  `preflight` texts per D-R1.13, `preflight` adds the version warning (`driver.probe`).
- `hive/tmux.py:91` `setup_pane(cfg, pane, pane_id)` gets the id from `prepare_launch` or
  `uuid4()`, expands with it, sets `@hive_session` after `@hive_name` (`:96`), returns the id;
  `start_pane` (`:102`) unchanged apart from passing the return value through. Invariant: tmux
  calls stay stubbable (`tests/test_cli.py` patches `tmux` by module).
- `hive/trust.py`: Claude-only, imported by `drivers/claude.py:5`; `looks_like_trust_prompt`
  stays for its tests.
- `hive/workers.py:29-49` `cmd_list`: `system=` on the queen, agent and pane lines, `waiting=
  <kind>` at `:48` (D-R1.4). Slice 4: `:129` `cmd_spawn --system NAME` (exclusive with
  `--launcher`), the launcher's `record["system"]` or the flag replaces `cfg["system"]` at
  `:147,158,212` and is passed to `append_agent`; driver default command when none given;
  `min_version` check for a new type; `:83` `parse_env_args` per D-R1.13.
  `hive/configedit.py:76` `append_agent(..., system=None)` writes `system = "..."` after
  `config_dir` (follow the `command`/`args` lines at `:80-83`). `hive/launchers.py:81`
  `launchers_add --system NAME` (check at `:91` uses it; the record gains `system`), `:134`
  `launchers_list` prints `system=`, `:162,183` `inspect-launcher --system`.
- `hive/inspect.py:13` `MATCH_RE` (imported from the claude driver): `inspect_launcher(command,
  roots, out, err, pattern=MATCH_RE)`.
- `hive/config.py:155-163` `check_env`, `:313` `parse_queen`, `:370` `parse_agents` (D-R1.12,
  D-R1.13).
- `hive/config.example.toml`: `system` at the four levels; OpenCode example with the XDG `[env]`
  lines for a test profile and the `pair --remote` note; Codex example with the daemon and
  `remote-control pair` note.
- Gotchas: `tests/conftest.py` deletes `XDG_*_HOME` and `CODEX_HOME` overrides tests set; never
  call `opencode debug ...` in hive (it auto-starts a service); the Codex TUI accepts input only
  after `› Ask Codex` appears (about 12 s), so validation sends prompts late; swarm's dev clone
  (D9) came from a bundle: ship the R1 branch with `git bundle create` + `scp` + `git fetch
  <bundle>` + `uv sync` before validating there.

## Slices

1. Claude driver complete (unit A: `hive/drivers/claude.py`, `hive/drivers/__init__.py`,
   `hive/trust.py`, `tests/test_drivers.py`, `tests/test_trust.py`; unit B: `hive/launch.py`,
   `hive/tmux.py`, `tests/test_args.py`). Delivers: every pane launches with `--session-id
   <uuid>`, `@hive_session` set, hooks and resume args available to R3/R4. Tests:
   `session_id_placeholder: command with {session_id} -> expanded once, no append`;
   `session_args_appended_when_absent: "claude -n {name} --remote-control {name}" -> ends with
   --session-id <uuid>`; `expand_pane_without_id_appends_nothing`; `uuid_per_pane: two
   setup_pane calls -> distinct uuid4`; `first_pane_gets_session: cmd_up with stubbed tmux ->
   set-option -p @hive_session <uuid> on the new-session pane`; `later_pane_gets_session:
   start_pane -> same`; `resume_args_claude -> ["--resume", id]`; `hook_args_claude:
   json.loads(args[1])["hooks"] has the four events, Notification matcher
   permission_prompt|idle_prompt`; `waiting_kind_theme: spike screen text -> "theme"`;
   `waiting_kind_login -> "login"`; `waiting_kind_trust: old phrases -> "trust"`;
   `waiting_kind_none: prompt screen -> None`; `looks_like_prompt_wrapper: theme screen -> False,
   trust screen -> True`; `probe_parses_claude: "2.1.311 (Claude Code)" -> "2.1.311"`;
   `get_driver_unknown_exits_2`. Checkpoint: `uv run --frozen pytest -q`.
2. Claude visible end to end (unit A: `hive/workers.py` `cmd_list`, `hive/drivers/claude.py`
   (drop `looks_like_prompt`), `tests/test_cli.py`; unit B: `docs/systems/claude.md`,
   `hive/config.example.toml` claude lines). Tests: `list_prints_system: default config -> queen
   and agent lines contain system=claude`; `list_waiting_kind: capture-pane stub returns the
   login screen -> pane line has waiting=login`; `list_waiting_trust_unchanged`. Checkpoint:
   `uv run --frozen pytest -q`; test hive: `uv run hive --profile test spawn <dir> --type cl
   --trust --config-dir ~/.config/hive/profiles/test/claude --command "sh -c
   'CLAUDE_CONFIG_DIR=$HOME/.config/hive/profiles/test/claude exec claude -n {name}
   --remote-control {name} --permission-mode auto --session-id {session_id}'"`, `up`, `list`
   shows `system=claude` and `waiting=theme`, `tmux -L hive-test show-options -p -t <pane>
   @hive_session` prints a uuid and `ps -o args= -p $(pgrep -f 'claude -n cl-test-1')` shows the
   same `--session-id`, `down`; `~/.claude.json` mtime unchanged; production listing unchanged.
3. Gates (user; no code; run after Slice 2 lands). OpenCode: `opencode upgrade`, `opencode
   service start`, `opencode pair --remote` (accept the expose prompt), scan the QR from a phone
   on mobile data, confirm the link host is an opentunnel relay, start `opencode` (no
   `--standalone`) in a terminal, send a prompt from the phone, see it in the TUI; pass when no
   tunnel or port-forward was needed. Codex: in the Codex or ChatGPT app open host swarm,
   project `~/.config/hive/profiles/test/codex-work`, find the chats titled "Reply ok" (one
   live), send a follow-up and see it in the hive pane (or repeat with a fresh `--profile test`
   Codex pane); when convenient, on swarm `codex remote-control stop` then `start` and check the
   app still lists the host (pairing persistence), and run `start` once more on the running
   daemon to see whether it errors (D-R1.10). Record one line per system, `- <date> decision:
   <system> gate pass on <version> | fail (<why>); source: user`, plus the `start` idempotency
   result, in `## Log`; set `min_version` from it. Checkpoint: both Log lines exist; a failed
   system drops its slice and gets an `Amend parent:` roadmap line.
4. Seam plumbing (after R2 lands; unit A: `hive/drivers/__init__.py` (`KNOWN_SYSTEMS`, texts),
   `hive/launch.py` probe wiring and D-R1.13 texts, `hive/inspect.py`, `hive/config.py`
   (`check_env`, `parse_queen`, `parse_agents`), `tests/test_drivers.py`, `tests/test_inspect.py`,
   `tests/test_config.py`; unit B: `hive/workers.py` `cmd_spawn` and `parse_env_args`,
   `hive/configedit.py`, `hive/launchers.py`, `tests/test_cli.py`, `tests/test_configedit.py`).
   Tests use the claude driver plus a fake driver inserted into `DRIVERS` through `monkeypatch`:
   `system_precedence: agent > launcher > defaults > claude (a launcher's system reaches the agent
   entry spawn writes)`; `spawn_system_flag: --system fake --command "fake" -> entry has system =
   "fake", no {name} required`; `spawn_system_without_command_uses_driver_default: --system fake
   -> entry command = fake.default_command, not [defaults] command`;
   `parse_agents_non_default_system_without_command -> driver default`;
   `spawn_system_with_launcher_is_usage_error`; `spawn_launcher_copies_system_and_checks_with_it:
   launcher system fake, command without --remote-control -> accepted, ensure_trust called with
   fake`; `launchers_add_system`; `append_agent_system_line`; `probe_below_min_version: fake min
   (9,0,0), --version 1.0.0 -> exit 2 naming install_hint`; `probe_binary_missing -> warning
   only`; `inspect_launcher_system_flag: --system fake with pattern FAKE_HOME, script line
   "export FAKE_HOME=/x" -> shown, "export OTHER=1" -> not shown`; `queen_system_unsupported ->
   exit 2`; `known_but_unregistered -> exit 2 "not in this release"`;
   `env_rejects_every_config_dir_env: fake config_dir_env FAKE_HOME in [env] -> exit 2 with the
   fake message`; `warn_untrusted_names_driver`. Checkpoint: `uv run --frozen pytest -q`.
5. OpenCode driver (if G1 passed; one unit: `hive/drivers/opencode.py`, its `DRIVERS` line,
   `tests/test_driver_opencode.py`, `docs/systems/opencode.md` stating version observed, remote
   model, one-time pairing, limitations). Spike step first (local, free model): with the four
   `XDG_*_HOME` under a scratch dir, `opencode service start`, `POST /api/session` with
   `{"directory": "<dir>"}` or `?directory=`, PATCH the title, then `opencode -s <id> <dir>` in
   a `--profile test` pane opens that session (capture-pane shows the title); record the body in
   `## Log`; if the TUI refuses an API-created id, use the fallback (`assigns_session_id =
   False`, `prepare_launch` returns `None`, launch without `-s`, note it for R3). Tests:
   `opencode_required_tokens_empty: command without --remote-control -> no warning`;
   `opencode_probe_v1: "1.19.4" -> exit 2 naming the install command`; `opencode_probe_ok:
   "opencode v2.2.0" -> accepted`; `opencode_config_dir_rejected -> exit 2`;
   `service_paths_from_env`; `prepare_launch_returns_api_id: fake urlopen records POST then
   PATCH title, returns ses_...`; `setup_pane_uses_api_id: @hive_session = ses_..., command has
   -s ses_...`; `session_args_opencode -> ["-s", id]`; `resume_args_opencode`;
   `hook_args_opencode -> []`; `waiting_kind_opencode_none`. Checkpoint: `uv run --frozen pytest
   -q`; test hive with `[env]` XDG vars under the profile dir: `spawn <dir> --type oc --system
   opencode`, `up`, `list` shows `system=opencode`, `curl` to the profile service lists a session
   titled `oc-test-1`, capture-pane shows `Ask anything`, `down`; `~/.config/opencode/*`
   unchanged.
6. Codex driver (if G2 passed; one unit: `hive/drivers/codex.py`, its `DRIVERS` line,
   `tests/test_driver_codex.py`, `docs/systems/codex.md`). Spike step first (local `codex`
   0.164.0, `git init` dir under the profile, no prompt sent): does `[projects."<dir>"]
   trust_level = "trusted"` in a throwaway `CODEX_HOME`'s `config.toml` suppress "Trust this
   folder?"; record in `## Log`. Tests: `codex_hook_args: contains -c hooks.SessionStart=... and
   --dangerously-bypass-hook-trust, TOML inline tables parse with tomllib`; `codex_resume_args ->
   ["resume", id]`; `codex_default_command_places_args_first`; `codex_trust_state_reads_config_toml`;
   `codex_seed_trust_appends_and_verifies`; `codex_seed_trust_refuses_existing_table`;
   `codex_seed_trust_refuses_unparseable`; `codex_env_rejects_CODEX_HOME`;
   `ensure_daemon_alive_pid_skips_start` (fake /proc check; replaced by
   `ensure_daemon_always_starts_once` when Slice 3 recorded `start` as idempotent);
   `ensure_daemon_starts_when_absent:
   fake subprocess records codex remote-control start`; `prepare_launch_with_config_dir_skips_daemon`;
   `waiting_kind_codex_trust`; `waiting_kind_codex_hooks_review`; `codex_probe: "codex-cli
   0.164.0" -> ok, "0.150.0" -> exit 2`. Checkpoint: `uv run --frozen pytest -q`; test hive
   here (the local daemon runs: under the pid rule `ensure_daemon` skips; under the
   always-start rule it would run `codex remote-control start` on the user's local daemon, so
   the executor asks the user before the default-home step): fresh home, `spawn <dir> --type cx
   --system codex --config-dir ~/.config/hive/profiles/test/codex --command "sh -c
   'CODEX_HOME=$HOME/.config/hive/profiles/test/codex exec codex {args} -a never -s
   workspace-write'"`, `up`, `list` shows `system=codex` and the dialog kind seen (expected
   `login`), `ps` shows `CODEX_HOME` in the pane's environment; then default home in a non-git dir
   under the profile: prompt appears, `codex agents` lists it; `down`; `~/.codex/config.toml`
   unchanged.
7. Example config and swarm check (unit A: `hive/config.example.toml` system examples, `tests/
   test_docs_links.py` run; unit B: none). Checkpoint: `uv run --frozen pytest -q`; if G2
   passed, the user runs on swarm (D9 clone on the R1 branch) `hive --profile test spawn <dir>
   --type cx --system codex`, `up`, `list`, `down`, and confirms in the app; agents only read the
   output (the swarm daemon is never started or stopped by an agent).

## Verification

After the last slice: `uv run --frozen pytest -q` green; CI green; in `--profile test` one Claude
worker (`waiting=theme`) and one worker per gated system that passed run side by side, `list`
shows `system=` for all and `@hive_session` on the Claude and OpenCode panes, `down`; `tmux -L
hive list-panes -s -F '#{pane_id} #{@hive_name}'` identical before and after; `~/.claude.json`,
`~/.config/opencode/*`, `~/.codex/config.toml` unchanged; if G2 passed, the user's swarm check of
Slice 7 shows `system=codex` and the app lists the worker.

## Risks

- `--session-id` appended to a wrapper launcher (`claude-supervisor ... --permission-mode auto`,
  the user's real config) relies on the wrapper passing unknown flags through; a user can place
  `{session_id}` explicitly. Documented in `docs/systems/claude.md`.
- Malformed inline hook JSON or `-c` TOML blocks a pane; tests round-trip both through
  `json.loads` and `tomllib.loads`.
- OpenCode docs run ahead of the binary (2.0.14 lacks `pair --remote`); `min_version` follows the
  gate; swarm (2.0.12) fails the probe until upgraded (user action).
- OpenCode `session.idle` and `permission.asked` event names are unverified live; R3 falls back to
  `/api/session/active` polling.
- `--dangerously-bypass-hook-trust` also trusts hooks from the user's own Codex config; documented.
- Codex sessions of test-hive workers in the default home land in `~/.codex/sessions` and in the
  app (unavoidable; the fresh-home variant covers dialog tests).

## Scope Notes

SAFETY CONTRACT of the parent binds: live checks only through `--profile test` (or
`spike-<name>`), never the default profile or socket `hive`; production pane listing recorded
before and after. Config dirs under the profile dir where the system allows it (Claude, OpenCode
via XDG `[env]`, Codex fresh-home variant); the Codex default-home check and the Codex gate use
the user's `~/.codex` by design (D-R1.9) and never write `~/.codex/config.toml`. Agents never run
`opencode pair --remote`, `opencode web`/`serve` on a non-loopback host, `opencode service
set|stop` on the user's shared service, or `codex remote-control start|stop|pair` on swarm; the
swarm Codex launch (Slice 7) is the user's.

User decisions not to reopen: ship only with tunnel-free other-device access (memory
`2026-10-27-ship-only-systems-with-tunnel-free-remote.md`); Codex is back in under that gate
(user, 2026-10-27, swarm pairing); OpenCode v2 is the generation; password exposure deferred.
Parent lead decisions bind: D7 (seam), D13 (fake worker), D17 (`@hive_session`). Out of scope: pi,
hook injection (R3), resume commands (R4), queens (R6), pairing subcommands.

## Assumptions

- R2 lands before Slice 2 starts; checked against the parent's R2 Status.
- `opencode service start` honours the caller's `XDG_*_HOME`; checked in the Slice 5 spike step.
- `POST /api/session` accepts a directory; checked in the Slice 5 spike step (fallback stated).
- `tests/test_docs_links.py` allows `docs/systems/` pages to appear (`PENDING_DIRS`); checked by
  running it.

## Open Questions

None: the two gates are scheduled user actions (Slice 3).

## Log

## Todo

- [x] Slice 1: claude driver methods, session id in `setup_pane`, `@hive_session`, waiting kinds
- [x] Slice 2: `hive list` `system=`/`waiting=<kind>`, `docs/systems/claude.md`, test-hive check
- [ ] Slice 3: user gates, one Log decision line per system, `min_version`, `start` idempotency
- [x] Slice 4: seam plumbing (`--system` on spawn/launchers/inspect, driver default command, probe, known-systems texts, env rejection)
- [ ] Slice 5: opencode driver and docs page (if G1 passed), spike step logged
- [ ] Slice 6: codex driver and docs page (if G2 passed), spike step logged
- [ ] Slice 7: example config; user-run swarm check
- [ ] Verification passes; production hive and user config dirs unchanged
