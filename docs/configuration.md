# Configuration

The config file is `${XDG_CONFIG_HOME:-~/.config}/hive/config.toml` (for a named profile, `.../hive/profiles/NAME/config.toml`; see [Test profile](test-profile.md)). Unknown keys are errors. `hive init` writes a commented template from `hive/config.example.toml`.

| Key | Meaning |
| --- | --- |
| `prefix` | Machine part of instance and window names (`[A-Za-z0-9_-]+`). Default: short hostname. |
| `session` | tmux session name. Default: `<prefix>-agents`. |
| `tmux_socket` | `tmux -L` server name. Default: `hive`. Set a different one in any test or isolated config, or it talks to your real hive. |
| `login_shell` | `true` (default): each pane runs `<shell> -l`, so your login profile applies. `false`: panes run tmux's `default-command`. |
| `shell` | Shell for `login_shell`. Default: your login shell from passwd, else `$SHELL`, else `/bin/sh`. |
| `search_roots` | Optional list of directories where `hive spawn NAME` looks for a directory `NAME`, and that `hive dirs` lists. `hive spawn` skips roots that do not exist; `hive dirs` reports them as `root=<path> error=missing`. `hive roots add\|remove PATH` edits it. |
| `inspect_roots` | Optional list of the only directories `hive inspect-launcher` reads from. Default: `["~/.local/bin", "/usr/local/bin", "/usr/bin", "/bin", "/opt"]`. |
| `[defaults] system` | Optional agent system that runs the commands. `claude` (the default) or `codex`; see [Claude](systems/claude.md) and [Codex](systems/codex.md). Also a key on `[queen]`, `[[agents]]` and `[[launchers]]`; precedence agent > launcher > defaults > `claude`. An agent whose system differs from `[defaults] system` and that has no `command` uses its system's default command. An unknown name is an error (exit 2) listing the known ones; `opencode`, which is deferred, gets `not in this release`. |
| `[defaults] command` | Command for every agent type without its own `command`. |
| `[defaults] launcher` | Optional name of the default launcher for new types: a `[[launchers]]` name or a `[queen] discover` name. Only checked against `[[launchers]]` at load; other names are looked up in discover when used. |
| `[defaults] args` | Optional list of non-empty strings, extra flags for the command (e.g. `["--fable"]`); see `args` below. A type's or the queen's own `args` replaces this list, it is not merged. Anything else is an error: `'<key>' must be an array of non-empty strings`. |
| `[queen] enabled` | `true` (default): the queen pane starts first. `false`: no queen; a running one is stopped by the next `up` or `reconcile`. With no queen and no agents, `hive up` prints `nothing to start: queen disabled and no agents` and exits 0 without a session. |
| `[queen] system` | Optional system for the queen. Default: `[defaults] system`. A system whose driver cannot run a queen is refused (exit 2). |
| `[queen] command` | Optional command for the queen. Default: `[defaults] command`, else `claude -n {name} --remote-control {name} --permission-mode auto --session-id {session_id}`. |
| `[queen] args` | Optional list of strings; replaces `[defaults] args`, no merge. hive appends its `--tools ... --strict-mcp-config` allowlist unless the command or these args already contain `--tools` or `--strict-mcp-config`. |
| `[queen] discover` | Optional shell command that `hive discover` runs; its output is printed as is. `hive spawn --launcher NAME` also runs it (timeout 60 s) and reads one record per line (see `hive discover`). |
| `[queen] config_dir` | Optional config dir of the queen's command. Only used to find the trust file (`<config_dir>/.claude.json` for Claude); never exported. |
| `[queen] env` | Optional inline table, same rules as `[[agents]] env`, for the queen's pane. |
| `[env]` | Optional `KEY = "value"` strings, exported in every pane before the command. See [Panes and environment](concepts.md#panes-and-environment). |
| `[service] after` | Optional list of units added to `After=` in `hive.service`. |
| `[[launchers]] name` | Required, unique, `[a-z0-9][a-z0-9-]*`. |
| `[[launchers]] system` | Optional system the launcher runs. Default: `[defaults] system`. `hive spawn --launcher` writes it into the new type when it differs from `[defaults] system`. |
| `[[launchers]] command` | Required; checked by the launcher's system (for Claude it must contain `{name}` and `--remote-control`). |
| `[[launchers]] config_dir` | Optional absolute path (`~/` expanded): the config dir the launcher uses; never exported. |
| `[[launchers]] description` | Optional free text. |
| `[[nodes]] name` | Required, unique, `[a-z0-9][a-z0-9-]*`: the `NAME` of `hive --node NAME`. See [Multi-node](multi-node.md). |
| `[[nodes]] host` | Required ssh destination (an `~/.ssh/config` alias or `user@host`); no whitespace, no leading `-`. |
| `[[nodes]] hive` | Optional remote hive executable, a single path or command name. Default: `hive`; a full path such as `/home/me/.local/bin/hive` is more robust. |
| `[[nodes]] profile` | Optional remote profile name, or `default`. Default: the remote default profile. Required (and not `default`) when `--node` is used from a named local profile. |
| `[[nodes]] description` | Optional free text. |
| `[[agents]] type` | Required, unique, not `queen` or `hive-queen`; letters, digits, `.`, `_` and `-` only. Window name is `<type>-<machine>`, `<machine>` being `prefix`. |
| `[[agents]] dir` | Required. Each pane starts with `cd <dir>`. If it does not exist, `up`, `restart` and `reconcile` skip that type's panes and start everything else, `hive list` marks the type `dir_missing=yes`, and `spawn` of that type is refused. |
| `[[agents]] count` | Number of panes, integer >= 0. Default: 1. `0` keeps the entry (dir, command, comments) without panes. Exclusive with `indices`. |
| `[[agents]] indices` | Instead of `count`: the explicit instance numbers, e.g. `indices = [2, 3]` for `<type>-<machine>-2` and `-3` only. `hive stop --index` writes it when the remaining numbers are not `1..N`, and `hive spawn` fills the lowest free numbers first (collapsing back to `count` when they are contiguous). `hive list` shows `indices=` for such a type. |
| `[[agents]] system` | Optional system of this type. Default: the launcher's when `hive spawn --launcher` chose one, else `[defaults] system`. With no `command`, the type runs `[defaults] command`, or its system's default command when its system differs from `[defaults] system`. |
| `[[agents]] command` | Optional override of `[defaults] command` (or of the system's default command). One of the two is required. |
| `[[agents]] args` | Optional list of non-empty strings, e.g. `args = ["--fable"]`; see `args` below. Replaces `[defaults] args`; `args = []` means none. |
| `[[agents]] env` | Optional inline table of string values, e.g. `env = { FOO = "bar" }`. Exported in that type's panes after the global `[env]`, so it wins. Unlike `[env]`, not set on the tmux server. |
| `[[agents]] config_dir` | Optional, e.g. `config_dir = "~/.claude-sandbox"`: the config dir that the type's command uses (a sandbox launcher's own dir). Only used to find the trust file (`<config_dir>/.claude.json` for Claude, `<config_dir>/config.toml` for Codex); never exported. |

Validation rules:

- `prefix` and `session` must be non-empty and contain no `.`, `:` or whitespace, since tmux rewrites or mis-targets such names.
- `tmux_socket` must be non-empty and contain no whitespace (`x.y` is valid).
- `search_roots` entries, `dir`, `config_dir` and `inspect_roots` entries must be absolute or start with `~` (expanded), and must not be empty.
- Commands and `shell` must not be empty.
- Env names (in `[env]`, `env` tables and `spawn --env`) must match `[A-Za-z_][A-Za-z0-9_]*`. Each system's config-dir variable (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`) is rejected everywhere, because hive never sets it; use `config_dir`.
- `count` and `indices` are exclusive on one `[[agents]]` entry; `indices` entries are distinct integers >= 1.

Placeholders in commands, replaced by plain text substitution (other braces such as `${VAR}` are untouched): `{name}` = `<type>-<machine>-<index>` (`<machine>` is `prefix`; index starts at 1), `{type}`, `{index}`, `{dir}`, `{prefix}`, `{session_id}` (a fresh UUID per pane launch; without it the driver's session flag is appended, for Claude `--session-id <uuid>`, see [Claude](systems/claude.md#session-id)), `{args}` (see below). `{session_id}` is also expanded in `args`.

`args` (optional on `[defaults]`, `[[agents]]` and `[queen]`) entries get the same placeholders expanded, are each shell-quoted (shlex) and joined by spaces. That string replaces every `{args}` in the command; without `{args}` it is appended at the end (nothing is added when there are no args). A launcher that takes its own flags before a `--` separator needs `{args}`, e.g. `command = "claude-supervisor run api {args} -- -n {name} --remote-control {name}"`; appended after `--` the args would go to claude.

## Applying changes

Run `hive up`: it reconciles a running session, so adding, removing or recounting agents needs no restart. Changes to `dir`, `command` or `args` of panes that are already running are not applied; stop and re-spawn them, or `hive restart`. Session-level keys (`prefix`, `session`, `tmux_socket`, `shell`, `login_shell`, and `[env]` for existing panes) also need `hive restart`.

Upgrading from the `<prefix>-<type>-<index>` naming: `hive up` and reconcile adopt those panes without a restart, renaming them in place (the queen from `<prefix>-queen` to `hive-queen-<machine>`). Their Remote Control session keeps its old name until restarted; a remote client bookmarked on `<host>-queen` must switch to `hive-queen-<host>` after the restart.
