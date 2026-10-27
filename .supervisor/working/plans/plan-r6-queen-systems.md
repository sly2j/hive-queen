# Plan: R6 queen on every supported system

Child plan of `.supervisor/working/plans/plan-hive-queen-2.0.md`, package R6, release `2.x`.
Binding items: see Scope Notes. Pointers are into `main` 2d109b0; `plan-r1-drivers.md` is cited
as D-R1.x, `plan-r3-done-detection.md` as D-R3.x, and
`.supervisor/working/research/2026-10-27-hive-queen-2.0-systems.md` as A5.

## Goal

The queen pane runs on each system that ships (D18), with equivalent instructions and command
guard: on Claude exactly as today, on OpenCode v2 and Codex behind a spike each. Slices 1-3 are
the ungated structure (shared `guard_core`, per-system layout, `--system` guard rule, docs);
units O (OpenCode) and C (Codex) are self-contained and droppable: a failed spike drops the unit
and adds an `Amend parent:` roadmap line.

Non-goals: resume (R4), `docs/systems/*.md` and the OpenCode/Codex drivers themselves (R1
Slices 5-6), status hooks (R3), pi, a Codex prompt mechanism beyond deny (roadmap, D-R6.11),
changing what the Claude guard allows or asks beyond the `--system` rule.

Expected change size: Slices 1-3 about 350 added or changed lines (`guard_core.py` carries
about 180 lines moved out of `guard.py`; `queen.md` carries about 65 lines moved out of
`CLAUDE.md`), unit O about 220 lines, unit C about 120 lines, each including tests and docs.

## Approach

1. Extract the system-neutral guard logic into `hive/queen/guard_core.py` that returns a verdict
   instead of exiting, and make `hive/queen/claude/hooks/guard.py` a thin adapter that maps the
   verdict to Claude's exit-2 / `ask` JSON protocol. `tests/test_guard.py` keeps every case and
   changes only two path constants. Rejected: three independent guard scripts (drift of the
   security rules across systems).
2. Move the Claude queen files under `hive/queen/claude/` and split the instructions into a
   common body `hive/queen/queen.md` plus a per-system `rules.md`; `materialize_queen` composes
   the instructions file and copies `guard_core.py` next to each adapter so the hooks stay
   standalone (D18). Rejected: per-system full copies of the 78-line instructions (three edits
   per text change); Claude `@import` (an import dialog can block a fresh pane, research A5).
3. Codex's PreToolUse payload has the same `tool_name` / `tool_input.command` shape as Claude's
   (worker report, learn.chatgpt.com/docs/hooks), so its adapter reuses the Claude adapter's
   input handling and maps `ask` to a deny that names the command for the user to run by hand
   (D18). OpenCode gets deny-first `permissions` rules plus a plugin that runs the same Python
   guard from `permission.hook("evaluate")` and sets `ask`/`deny`, so its prompts are real.
4. Each gated unit starts with a spike in the test profile with explicit pass criteria; the unit
   is dropped on failure. The structural slices land as their own squash before any gated unit,
   because units O and C wait for R1 Slices 5/6 (user gates G1/G2).

## Decisions

- D-R6.1 Layout. `hive/queen/queen.md` (common instructions body, today's `CLAUDE.md` minus
  `## Rules`), `hive/queen/guard_core.py`, `hive/queen/claude/{rules.md,settings.json,
  hooks/guard.py}`, `hive/queen/opencode/{rules.md,opencode.json,plugins/guard.ts,
  hooks/guard.py}` (unit O), `hive/queen/codex/{rules.md,hooks/guard.py}` (unit C). Destination
  paths in the queen dir are unchanged for Claude (`CLAUDE.md`, `.claude/settings.json`,
  `.claude/hooks/guard.py`) plus `.claude/hooks/guard_core.py`; OpenCode writes `AGENTS.md`,
  `opencode.json`, `.opencode/plugins/guard.ts`, `.opencode/hooks/{guard.py,guard_core.py}`;
  Codex writes `AGENTS.md`, `.codex/hooks/{guard.py,guard_core.py}`.
- D-R6.2 `guard_core` API: stdlib only, no `hive` import, no `print`/`sys.exit`. It owns the
  constants `CHAIN`, `BASH_REASON`, `PRIVATE_PARTS`, `NODE_RE`, `GLOB_CHARS`,
  `SPAWN_VALUE_OPTIONS` and the functions `config_commands`, `config_args`, `config_systems`
  (new), `spawn_options`, `has_flag`, `spawn_target`, `is_private`, `resolve`, `check_glob_parts`
  (`hive/queen/hooks/guard.py:54-140, 225-230`), and `check_bash(command, qdir) -> Verdict`,
  `check_path(text, qdir, write, protected) -> Verdict`, `check_file_tool(tool, tool_input,
  qdir, protected) -> Verdict` (`:143-258`). `Verdict` is a `NamedTuple(decision, reason)` with
  decision in `allow|ask|deny`. Internally `block()` raises a `Deny` exception and the ask
  reasons collect as today, so the order "deny wins over ask" and every reason string stay
  identical. Tool-name sets (`QUEEN_TOOLS`, `FILE_TOOLS`, `SHELL_TOOLS`, `WRITE_TOOLS`,
  `DIALOG_TOOLS`) and `PROTECTED_NAMES` are system-specific and stay in each adapter.
- D-R6.3 Adapter import. An adapter does `import guard_core`: Python puts the script's own
  directory first on `sys.path`, which finds the copy materialized next to it; for the repo
  layout the adapter appends `Path(__file__).resolve().parents[2]` (the `hive/queen` dir) only
  when no sibling `guard_core.py` exists. Never put the queen dir itself on the path: the queen
  can write there.
- D-R6.4 `--system` guard rule (R1 deferral). `hive spawn ... --system X` (also `--system=X`
  and abbreviations down to `--sys`) answers `ask` unless X is a system already named in
  `../config.toml` (`[defaults] system`, `[queen] system`, any `[[agents]] system`, any
  `[[launchers]] system`), through `config_systems(qdir)` shaped like `config_args`; a missing
  or unreadable config asks, like `--command`. Reason text: `hive spawn --system starts a
  different agent system: X`. Why: a new system is a new binary with its own trust model and,
  for OpenCode and Codex, a service or daemon side effect (D-R1.6, D-R1.10); a system the user
  already configured is their choice. Rejected: pass-through (today's interim; the queen could
  switch systems silently) and always-ask (noisy once a second system is configured).
  `SPAWN_VALUE_OPTIONS` gains `--system` and `--resume` (R4's value option) so `spawn_target`
  keeps naming the right target in the `--trust` prompt (`hive spawn --system codex x --trust`
  names `x`, not `codex`). On Codex this rule is a deny like every other `ask` (D-R6.9).
- D-R6.5 `materialize_queen` (`hive/queen.py:28-49`). For `dest == driver.instructions_file`
  the data is `QUEEN_HEADER + queen.md + "\n" + <packaged src>` where `src` is the system's
  `rules.md`; `QUEEN_HEADER` becomes system-neutral (`<!-- managed by hive; do not edit -->`,
  the local-additions hint lives in each `rules.md` and in docs). A module table `RENDERERS =
  {"claude/settings.json": queen_settings, ...}` keyed by packaged path replaces the
  `src == "settings.json"` branch (`:39-40`); unit O adds `"opencode/plugins/guard.ts"` with the
  same `python3 -> sys.executable` substitution. Every system's `queen_files` lists
  `guard_core.py` as a plain copy. Unchanged bytes are still not rewritten.
- D-R6.6 Common text. `queen.md` drops "Claude" from the intro, says "use the question tool
  named in Rules" instead of `AskUserQuestion`, states the manual `--command` rule as "what the
  worker's system requires (claude: `{name}` and `--remote-control`)", and names the config-dir
  variable per system in "Inferring a launcher's config dir" with `hive inspect-launcher "CMD"
  --system NAME` for a non-default system (R1 Slice 4 landed the flag). The `## Workspace
  trust` section (`CLAUDE.md:62-67`, Claude config dirs and `.claude/settings.json`) moves into
  `claude/rules.md`; `queen.md` keeps one neutral sentence: `hive spawn` exits 3 with
  `untrusted: ...` when the worker's system does not trust the directory; follow Rules for
  what to do. The `hive list` bullet carries R3's `state=` sentence (R3 Slice 2, lands before
  R6). Each `rules.md` holds the tool list, the guard mechanics, the prompt (or deny) list,
  the trust directions for its worker systems and the local-additions file.
- D-R6.7 Drivers. `supports_queen = True`, `queen_files` and `queen_extras` land only in the
  unit that passes its spike (`hive/drivers/opencode.py`, `hive/drivers/codex.py`, R1 Slices
  5/6 own the rest of those modules). `parse_queen` already exits 2 for `supports_queen = False`
  (`hive/config.py:372-374`, test `tests/test_config.py:612`), so "selection by `[queen]
  system`" needs no new config code; `hive/queen.py` dispatches on `cfg["queen"]["system"]`
  (`:30`). `queen_extras` keeps its `(command, args)` signature: a per-launch path is written
  as the `{dir}` placeholder, which `expand_pane` expands to the queen dir
  (`hive/launch.py:51-52`).
- D-R6.8 OpenCode queen (unit O; worker report from opencode.ai/v2/docs permissions, tools,
  build/plugins, instructions). `opencode.json` in the queen dir: `default_agent: "queen"`,
  `instructions: ["AGENTS.local.md"]`, and an ordered `permissions` list: `{action:"*",
  resource:"*", effect:"deny"}` first; then allow `read`, `glob`, `grep`, `edit` (covers write
  and patch) and `question` on `*`; deny `external_directory` on `*` (the default policy allows
  it); deny `read` and `edit` on `*secrets*`, `*private*`, `*.env*`; deny `edit` on `AGENTS.md`,
  `opencode.json`, `.opencode/*`; shell allow `hive *`; shell ask `hive down*`, `hive restart*`,
  `hive roots add*`, `hive launchers add*`. Last matching rule wins per resource, any deny wins
  across the resources of a compound command, so `hive list; ls` is denied by the `ls`
  resource. `.opencode/plugins/guard.ts` registers `ctx.permission.hook("evaluate")`: for actions
  `shell`, `read`, `edit`, `glob`, `grep` it runs `python3 .opencode/hooks/guard.py` (Bun
  subprocess, JSON `{action, resources}` on stdin) and sets `event.effect` and `event.message`
  from the verdict; a hook runs only for allow/ask decisions, so the configured denies stay the
  floor. The OpenCode adapter maps `shell` with one resource to `check_bash` (more than one
  resource is chaining: deny) and `read`/`edit` resources to `check_path`, protected names
  `AGENTS.md`, `opencode.json`, `.opencode`; for `glob`/`grep` the resource is the pattern,
  so the adapter applies `check_glob_parts` and `is_private` to it, and directory bounding is
  the configured `external_directory` deny. `queen_extras` removes a standalone `--auto`
  token from the command and from the args (`[queen] args` or inherited `[defaults] args`,
  `hive/config.py:361-363`; the driver default command has it, D-R1.6): `--auto` auto-approves
  everything not denied, which would turn `ask` into allow. No CLI flag restricts tools or MCP in v2, so
  restriction is config only. Rejected: `tool.hook("execute.before")` with a throw as the
  primary mechanism (deny only, blocking by throw undocumented); a TypeScript port of the guard
  (two sources of truth).
- D-R6.9 Codex queen (unit C; worker report from learn.chatgpt.com/docs/hooks,
  config-reference, rules, agents-md). PreToolUse via `queen_extras`: `-c
  'hooks.PreToolUse=[{matcher=".*",hooks=[{type="command",command="<sys.executable>
  {dir}/.codex/hooks/guard.py",timeout=30}]}]'` plus `-c web_search="disabled"`, `-c
  tools.view_image=false`, `-c features.multi_agent=false`, `-c features.apps=false` (hosted
  tools are outside hook coverage), `-c features.unified_exec=false` (removes
  `exec_command`/`write_stdin`: stdin sent after an allowed command is not re-checked by
  PreToolUse, research A5) and `-s danger-full-access` replacing `-s workspace-write`
  (the queen must write `../config.toml`, connect to the tmux socket and ssh for `--node`; the
  guard is the barrier, as `--permission-mode auto` is for Claude). `-a never` stays:
  PreToolUse cannot `ask`, an `ask` answer is logged and the call proceeds, so the Codex adapter
  turns every `ask` verdict into a deny whose reason says `codex cannot ask for confirmation;
  tell the user to run this by hand: <command>`. Tool names: `Bash` (shell and exec_command,
  `tool_input.command` string), `apply_patch` (paths parsed from `*** Add/Update/Delete File:`
  and `*** Move to:` lines, source and destination each checked with `check_path` as a write,
  protected `AGENTS.md`, `AGENTS.override.md`, `.codex`),
  `update_plan` allowed (no side effect), everything else (`mcp__*`, `spawn_agent`,
  `view_image`, unknown) denied. The adapter denies with exit 2 and a non-empty stderr (an
  empty stderr is not a block). `--dangerously-bypass-hook-trust` is appended by R3's
  `hook_args`, not by `queen_extras`, so unit C needs R3 Slice 4 landed. The `-c` hook table
  merges per dotted key with R3's `hooks.SessionStart` etc. (inferred; spike step). No local
  additions file: `AGENTS.override.md` in the queen dir would replace `AGENTS.md`, so the Codex
  `rules.md` says additions go in the user's global `$CODEX_HOME/AGENTS.md`. No question tool:
  the numbered-choices fallback of `queen.md` applies. Rejected for this release: `-a
  on-request` plus `.codex/rules/*.rules` `prefix_rule(..., decision="prompt")` for real prompts
  (needs the queen dir trusted via `-c projects`, prefix-only matching, `allow` rules bypass the
  sandbox); roadmap, D-R6.11.
- D-R6.10 Spike protocol (both units), from a worktree, test profile only, Scope Notes recipe:
  record `tmux -L hive list-panes -s -F '#{pane_id} #{@hive_name}'` before and after;
  `[queen] enabled = true`, `[queen] system = <system>`, `[queen] command` set explicitly to
  the driver's default (the reused profile's `[defaults] command` is the fake worker). The
  executor first writes the unit's files and the driver flip (`supports_queen = True`,
  `queen_files`, `queen_extras`) in the worktree, since `parse_queen` refuses an enabled queen
  before the flip (`hive/config.py:372-374`); the spike runs from that worktree: the executor
  starts `hive --profile test up`, the user drives the queen from a terminal outside the hive
  (`tmux -L hive-test attach`), reading the pane; the executor reads the transcript and `hive
  --profile test list`. Pass criteria (hard): `hive list` runs without a prompt; `hive list;
  ls` is denied with a reason visible to the agent (OpenCode: the configured rule; Codex:
  `guard:`); `hive down` and `hive spawn <dir> --trust` do not run unprompted (OpenCode: the
  TUI prompts and the user declines; Codex: a deny naming the command for the user); a read
  of `/etc/hostname` and, on OpenCode, a `grep` with path `/etc` are denied; `hive list` shows
  the queen's state (Codex: `source=hook`, the `-c` hook tables merged and
  `state/status/hive-queen-*.json` written; OpenCode: `source=api`, D-R3.5). Soft
  (OpenCode): if `ask` does not prompt, the plugin maps `ask` to deny like Codex and the docs
  say so; that is not a spike failure. A hard failure drops the unit: the branch is discarded,
  `supports_queen` stays `False`, only the `docs/queen.md` limitation line lands, and the
  report carries `Amend parent: roadmap: queen on <system> (spike failed: <reason>)`. On a
  pass the unit's tests and docs complete on the same branch. Teardown in the same
  session: `hive --profile test down`; `~/.codex/config.toml` and `~/.config/opencode/*`
  hashes unchanged. Codex runs in the default `CODEX_HOME` (amended D18), so before the Codex
  spike the executor asks the user (R1 Slice 6 rule: `ensure_daemon` may run `codex
  remote-control start` on the user's daemon); the queen dir is not a git dir, so Codex shows no
  trust prompt and hive seeds nothing (D-R1.9).
- D-R6.11 Roadmap item this plan creates: Codex rules-based prompts (`-a on-request` plus a
  `.codex/rules` file) replacing deny-with-message.

## Outline

- `hive/queen/guard_core.py` (new): the API of D-R6.2; `class Deny(Exception)`; `block(reason)`
  raises it; `check_bash` returns `Verdict("ask", "; ".join(reasons) + f"{where}; approve to
  run it")` exactly as `guard.py:194` prints today. Gotcha: `is_private` reads `sys.platform`
  at call time (test `tests/test_guard.py:347-357` monkeypatches it on the loaded module).
- `hive/queen/claude/hooks/guard.py` (moved with `git mv`, then cut): docstring, tool sets,
  `PROTECTED_NAMES`, `block`, `ask` (`guard.py:41-51`), `main` (`:261-283`) calling
  `guard_core` and mapping the verdict; the `try/except Exception -> block` stays (fail closed).
- `hive/queen/claude/settings.json`, `hive/queen/claude/rules.md` (`## Workspace trust` and
  `## Rules`, `hive/queen/CLAUDE.md:62-78`, plus the `--system` prompt in the list and the
  `CLAUDE.local.md` sentence); `hive/queen/queen.md` (`CLAUDE.md:1-61` with the D-R6.6 edits;
  `git mv CLAUDE.md queen.md` keeps history).
- `hive/queen.py`: `QUEEN_HEADER`, `RENDERERS`, `compose_instructions(pkg, driver)`,
  `materialize_queen` loop per D-R6.5; `die` on `OSError` unchanged (`:48-49`).
- `hive/drivers/claude.py:40-42`: `queen_files = {"CLAUDE.md": "claude/rules.md",
  ".claude/settings.json": "claude/settings.json", ".claude/hooks/guard.py":
  "claude/hooks/guard.py", ".claude/hooks/guard_core.py": "guard_core.py"}`.
- `pyproject.toml:27-28`: package-data globs `queen/*`, `queen/claude/*`,
  `queen/claude/hooks/*`, and per unit `queen/opencode/*`, `queen/opencode/hooks/*`,
  `queen/opencode/plugins/*`, `queen/codex/*`, `queen/codex/hooks/*` (setuptools globs do not
  recurse). R3 adds `hooks/*` on the same line; R6 edits the landed line.
- Tests. `tests/test_guard.py:9` `GUARD` to the new path; `:347-357` loads `guard_core.py`
  for `is_private`; nothing else changes. `tests/test_split.py:86-87` new path plus
  `test_guard_core_is_standalone`. `tests/test_cli.py:317-323, 373-385` move to
  `tests/test_queen.py` (new); `tests/test_cli.py:521-528` points at the new adapter path.
  Fixture: `tests/conftest.py:33-93` `FakeDriver` / `fake_driver` (set `queen_files` and
  `instructions_file` on the instance in a test).
- `docs/queen.md`: the layout paragraph (`:7`) becomes a per-system table of managed files;
  the security model (`:13-30`) becomes "Shared rules" plus a subsection per system; a
  `[queen] system` paragraph; the `--system` prompt joins the list at `:19-26`; limitations per
  system (Codex: no prompts, no local additions; OpenCode: no `--auto`, prompts need the TUI or
  web client).
- Unit O: `hive/queen/opencode/opencode.json` (D-R6.8), `plugins/guard.ts` (about 40 lines:
  `Plugin.define`, `permission.hook("evaluate")`, `Bun.spawn` of the adapter, JSON verdict ->
  `event.effect`/`event.message`), `hooks/guard.py` (adapter: stdin `{action, resources}`),
  `rules.md`; `hive/drivers/opencode.py`: `queen_files`, `supports_queen = True`,
  `queen_extras` strips `--auto`; `RENDERERS["opencode/plugins/guard.ts"]`;
  `tests/test_guard_opencode.py`, `tests/test_queen.py` additions.
- Unit C: `hive/queen/codex/hooks/guard.py` (adapter: Claude's input handling, `apply_patch`
  path parsing, ask -> deny), `rules.md`; `hive/drivers/codex.py`: `queen_files`,
  `supports_queen = True`, `queen_extras` of D-R6.9 (the `-c` values shell-quoted with
  `shlex.quote`; `{dir}` inside the quoted TOML string; a `'` in the profile path breaks it,
  documented); `tests/test_guard_codex.py`, `tests/test_queen.py` additions.
- Invariants: `guard_core.py` and every adapter import nothing from `hive`; an adapter never
  emits `ask` on a system without it; `materialize_queen` writes only under the queen dir;
  the production hive and the default profile are never touched (Scope Notes).

## Slices

1. Shared guard core and per-system layout (unit A: `hive/queen/guard_core.py`,
   `hive/queen/claude/*`, `hive/queen/queen.md`, `tests/test_guard.py`, `tests/test_split.py`;
   unit B: `hive/queen.py`, `hive/drivers/claude.py`, `pyproject.toml`, `tests/test_queen.py`,
   `tests/test_cli.py` pointer and moved tests, `docs/queen.md` layout table). Tests:
   `test_guard.py` all existing cases green with only the two path constants changed;
   `guard_core_is_standalone: no hive import`;
   `materialize_claude_composes_instructions: CLAUDE.md == header + queen.md + "\n" +
   claude/rules.md`; `materialize_copies_guard_core: .claude/hooks/guard_core.py == packaged
   bytes, and the materialized guard.py run with CLAUDE_PROJECT_DIR=<qdir> allows {"tool_name":
   "Bash", "tool_input": {"command": "hive list"}}`; `materialize_fake_system: fake driver with
   instructions_file AGENTS.md and queen_files {"AGENTS.md": "claude/rules.md"} -> AGENTS.md
   written with the header and queen.md, CLAUDE.md absent`;
   `materialized_guard_hook_uses_hives_interpreter` (its packaged resource path changed to
   `queen/claude/settings.json`, `tests/test_cli.py:378`) and `materialize_queen_dies_on_oserror`
   moved; `packaged_queen_files_exist: every queen_files src of every DRIVERS entry
   exists under resources.files("hive")/"queen"`. Checkpoint: `uv run --frozen pytest -q`;
   `uv build` then `python -m zipfile -l dist/*.whl | grep queen/` lists `queen.md`,
   `guard_core.py` and the three `claude/` files.
2. `--system` guard rule (unit A: `hive/queen/guard_core.py`, `tests/test_guard.py`; unit B:
   `hive/queen/claude/rules.md`, `hive/queen/queen.md` spawn bullet, `docs/queen.md` prompt
   list). Tests: `spawn_system_unlisted_asks: "--system", "--system=codex", "--sys" with
   [defaults] system = "claude" -> ask naming codex`; `spawn_system_listed_allowed: [[agents]]
   system = "codex" -> no ask`; `spawn_system_without_config_asks`; `spawn_system_and_trust_one_
   reason: both reasons in one prompt, target is the directory`; `spawn_target_skips_system_and_
   resume: "hive spawn --system codex --resume w x --trust" -> target x`; `system_denied_with_
   chaining`. Checkpoint: `uv run --frozen pytest -q`.
3. Claude queen live check in the test profile (user-run; no code). Setup per D-R6.10 with
   `[queen] system = "claude"`, `[queen] config_dir = <profile dir>/claude` and the R0 leftover
   profile (attach once for login if the config dir is fresh, D-R1.2). Steps the user runs in
   the queen: `hive list` (runs), `hive list; ls` (blocked), `hive spawn <dir> --system codex`
   (prompt names codex; decline), `hive down` (prompt; decline); `hive --profile test down`
   from the executor. Checkpoint: the four outcomes recorded in `## Log`; pane listing diff
   empty; `~/.claude.json` unchanged. Land Slices 1-3 as one squash (`feat/r6-queen-systems`).
4. Unit O, OpenCode queen (one unit; Deps: R1 Slice 5 landed, `opencode >= min_version`
   installed locally). Spike first per D-R6.10 with a profile whose `[env]` sets the four
   `XDG_*_HOME` under the profile dir (its own service, D-R1.7); extra checks: the service
   loaded the queen dir's `opencode.json` and plugin (a `read` of `/etc/hostname` is denied;
   `hive down` prompts); record outcomes and the `--auto`-less prompt behaviour in `## Log`.
   Then: tests `opencode_adapter_shell_allow: {"action":"shell","resources":["hive list"]} ->
   allow`; `opencode_adapter_two_resources_deny`; `opencode_adapter_ask_down`;
   `opencode_adapter_read_outside_deny`; `opencode_adapter_protected_edit_deny: opencode.json`;
   `opencode_adapter_glob_dotdot_deny: pattern "../*" -> deny`;
   `opencode_queen_extras_strips_auto: "opencode --auto -s {session_id} {dir}" -> no --auto,
   also from args ["--auto", "-x"] -> ["-x"], idempotent`;
   `materialize_queen_per_system: [queen] system = "opencode" -> AGENTS.md,
   opencode.json, .opencode/plugins/guard.ts (python3 replaced by sys.executable),
   .opencode/hooks/{guard.py,guard_core.py} written, no .claude or CLAUDE.md`;
   `opencode_json_rules_shape: first rule deny-all, every rule has action/resource/effect`.
   Checkpoint: `uv run --frozen pytest -q`; the spike criteria; `docs/queen.md` OpenCode
   subsection. Lands as its own squash.
5. Unit C, Codex queen (one unit; Deps: R1 Slice 6 and R3 Slice 4 landed). Spike first per
   D-R6.10 (default `CODEX_HOME`, executor asks the user first); extra checks: the deny reason
   is visible in the pane, `codex` starts with the six `-c` values (no unknown-key error) and
   its shell tool still runs `hive list`; record in `## Log`. Then: tests
   `codex_adapter_allows_hive_list`; `codex_adapter_denies_chaining`;
   `codex_adapter_ask_becomes_deny: "hive down" -> exit 2, stderr names the command and "run
   this by hand"`; `codex_adapter_apply_patch_inside_allowed / _outside_denied / _protected_
   denied: "*** Update File: AGENTS.md"`; `codex_adapter_apply_patch_move_outside_denied: "***
   Update File: notes.md" then "*** Move to: ../config.toml" -> deny`;
   `codex_adapter_denies_mcp_and_unknown: mcp__x__y, view_image, spawn_agent`;
   `codex_adapter_allows_update_plan`; `codex_adapter_every_ask_is_deny: for every ask input
   of tests/test_guard.py (spawn --command/--arg/--env/--trust/--system, roots add, launchers
   add, down, restart, their --node forms) -> exit 2, no stdout, stderr names the command`;
   `codex_queen_extras: contains -c hooks.PreToolUse with {dir}/.codex/hooks/guard.py and
   sys.executable, web_search="disabled", -s danger-full-access, no workspace-write, each
   value parses as TOML, idempotent`; `materialize_codex_queen: AGENTS.md and
   .codex/hooks/{guard.py,guard_core.py}, nothing else`. Checkpoint: `uv run --frozen pytest
   -q`; the spike criteria; `docs/queen.md` Codex subsection. Lands as its own squash.

## Verification

`uv run --frozen pytest -q` green on 3.11-3.13 (CI); `tests/test_guard.py` case count equal to
today's; wheel contents list every `queen_files` source of every registered driver; one real
queen per shipping system in the test profile passed D-R6.10 (Slice 3 and the spikes), each
torn down in its session; production pane listing identical before and after every live
session; `~/.claude.json`, `~/.codex/config.toml`, `~/.config/opencode/*` unchanged; a failed
unit left `supports_queen = False`, a `docs/queen.md` limitation line and an `Amend parent:`
line in the report.

## Risks

- OpenCode: the shared service resolving project config and plugins per session directory is
  inferred from the docs ("per location"), not verified; if it does not, unit O fails hard
  (no guard at all). `**` in resource patterns is undocumented (`*` matches `/`), so the
  secrets patterns use `*secrets*`. Local `opencode` is 2.0.14 and the target is >= 2.2.0: the
  user upgrades before the spike (R1 Slice 5 needs the same).
- Codex: a hook that crashes or exits with a code other than 0 or 2 does not block (fail open);
  the adapter catches everything and exits 2, and a missing script makes Python exit 2 as well,
  but an unusable interpreter path fails open. The deny reason reaching the model is inferred.
  `-c` parsing of a nested inline-table array with quotes is unverified. `danger-full-access`
  makes the guard the only barrier, as on Claude.
- Guard behaviour must stay byte-identical on Claude: the refactor is covered by the existing
  `tests/test_guard.py` cases, and any reason-text drift shows only there.

## Scope Notes

In scope: `hive/queen/*`, `hive/queen.py`, `hive/drivers/opencode.py` and `codex.py`
(`supports_queen`, `queen_files`, `queen_extras`), `hive/drivers/claude.py:40-42`,
`pyproject.toml` package data, `tests/test_guard.py`, `tests/test_queen.py` (new),
`tests/test_guard_opencode.py`, `tests/test_guard_codex.py`, `docs/queen.md`, plus the pointer
edits in `tests/test_cli.py` and `tests/test_split.py` (reported as `Amend parent:` Owns).
Out of scope: `docs/systems/*.md`, `hive/config.py`, `hive/workers.py`, the Driver protocol,
R4 resume, R8b polish, a Codex prompt mechanism (D-R6.11), pi.

Binding and not to be reopened by `executor`: the queen on every supported system (memory
`2026-10-27-queen-runs-on-every-supported-system.md`); a failed spike ships worker-only, the
release is not held (parent Log 2026-10-27); D18 as amended (layout, shared `guard_core`
copied into each queen dir, OpenCode `permissions` plural, shared service, Codex default
`CODEX_HOME`); the safety contract of the parent Scope Notes (test profiles only, never the
default profile or the `hive` socket here or on swarm, no `hive attach` from inside the hive,
pane listing before and after); R5's `--node NAME` shift stays in `guard_core.check_bash`.
The executor runs no real agent itself: Slice 3 and the spikes are driven by the user from a
terminal outside the hive, the executor sets up, reads and tears down.

## Assumptions

- R3 has landed on `main` before Slice 1 starts (its `hive/queen/CLAUDE.md` bullet and
  `pyproject.toml` `hooks/*` glob are then part of the move); checked with `git log main --
  hive/hooks/status_hook.py`.
- The R0 leftover test profile on this machine still has a logged-in Claude config dir;
  checked by `hive --profile test list` showing no `waiting=` for the queen after `up`.
- Bun's `Bun.spawn` is available inside an OpenCode plugin (plugins run in the Bun-based
  server); checked by the unit O spike (fallback: `node:child_process`).
- Codex's `-c` dotted hook keys merge with R3's instead of replacing the `hooks` table;
  checked in the unit C spike by the status file appearing.

## Open Questions

None that need the user before the structural slices. Both gated units hinge on their spike,
whose pass and fail paths are decided (D-R6.10).

## Log

- 2026-10-27 R6 unit C (executor): spike on swarm Codex 0.164.0: project `.codex/hooks.json` in the queen dir keeps the pane on the shared daemon (no embedded-mode warning, `-a never -s danger-full-access` fine) but needs folder trust (`[projects]`) and hook trust stored as `[hooks.state."<key>"] trusted_hash` in the user's ~/.codex/config.toml, re-requested when the hook hash changes; stopped before hook trust per the safety contract, user config restored, panes unchanged on both machines
- 2026-10-27 amend D-R6.10 (R6 child plan): a non-git queen dir with `.codex/` does show Codex's folder-trust prompt; "no trust prompt, hive seeds nothing" is wrong; seed_trust for the queen dir is acceptable
- 2026-10-27 decision: user: allow Codex to persist the queen's folder and hook trust in ~/.codex/config.toml (one interactive "Trust all"; re-trust after guard changes is an accepted upgrade step); Codex queen ships; unit C resumed on feat/r6-codex-queen

## Todo

- [x] Slice 1: `guard_core.py`, `claude/` layout, `queen.md` + `rules.md`, composed
      materialize, package data, test pointers, `tests/test_queen.py`, docs layout table
- [x] Slice 2: `--system` guard rule, `SPAWN_VALUE_OPTIONS`, rules and docs prompt list
- [x] Slice 3: Claude queen live check in the test profile (user-run), outcomes in `## Log`;
      squash-land Slices 1-3
- [ ] Unit O: spike (criteria D-R6.10) recorded; on pass `opencode.json`, plugin, adapter,
      driver flip, tests, docs; on fail limitation line and `Amend parent:` roadmap — dropped (G1 fail, OpenCode deferred)
- [ ] Unit C: spike recorded; on pass adapter, `queen_extras`, driver flip, tests, docs; on
      fail limitation line and `Amend parent:` roadmap
- [ ] Verification passes; production hive and user config dirs unchanged
