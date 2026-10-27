# Commands

| Command | Does |
| --- | --- |
| `hive up` | Start the session if it is not running, with the queen first. Prints `started session <session> (tmux -L <socket>)`, then `started <name>  [<dir>]  <command>` per pane. If it is running, reconcile it with the config (same output as `hive reconcile`). Types whose `dir` is missing are skipped with a summary warning, and the exit code stays 0. If startup fails, hive removes the half-built session. |
| `hive down` | Kill the session, and the hive tmux server once it is empty. Prints `stopped session <session>`, or `session <session> not running` (exit 0). Works with a broken `config.toml`: it warns `config problem: ...` and takes `prefix`, `session` and `tmux_socket` from the config's parsable top-level lines, falling back to the defaults for names the config does not set. A name that is set but invalid is still an error (exit 2). |
| `hive restart` | `systemctl --user restart hive.service` if that unit is active, else `down` then `up`. |
| `hive status` | Prints `session <session>`, then one line per window and one per pane (`pane <index>: <title>  (<command>)`), then `attach: tmux -L <socket> attach -t <session>`. Exit 1 and `not running` if the session is not running. Works with a broken `config.toml`, like `down`. |
| `hive attach` | Attach to the session (exit 1 if not running). |
| `hive list` | Config and running state side by side, as `key=value` lines. See [hive list](#hive-list). |
| `hive spawn TARGET [-n N] [--type TYPE] [--command CMD \| --launcher NAME] [--config-dir PATH] [--env KEY=VALUE ...] [--arg ARG ...] [--trust]` | Add N workers of a type or a new directory, then reconcile. See [hive spawn](#hive-spawn). |
| `hive stop TARGET [-n N]` | Remove N workers (default 1) of an existing type: lower `count`, then reconcile. The highest indices go first; the entry stays at `count = 0`. |
| `hive reconcile [--dry-run]` | Make the running session match the config: adopt panes titled with a configured pane name (`adopted <name>`), start missing panes, stop managed panes no longer in the config (`stopped <name>`), leave unmanaged panes alone, never stop the queen. Prints `no changes` when there is nothing to do. `--dry-run` only prints `would start <name>`, `would stop <name>` and `would skip <name>: dir <dir> does not exist`. Exit 1 if not running. |
| `hive discover` | Run `[queen] discover` and print its output verbatim. See [hive discover](#hive-discover). |
| `hive launchers` | List the known launchers, one `launcher name=N source=config\|discover default=yes\|no config_dir=<path\|default> command=<cmd> [description=...] [shadowed=yes]` record each: the default first, then the registry, then `[queen] discover` records. See [Launchers](launchers.md). |
| `hive launchers add NAME COMMAND [--config-dir PATH] [--description TEXT]` | Append a `[[launchers]]` entry to `config.toml`. NAME matches `[a-z0-9][a-z0-9-]*` and is not already a registry or discover name (exit 2). COMMAND must contain `{name}` and `--remote-control`, and its executable (first word) must exist on `PATH` or as a path (exit 2) and not be under a `secrets`/`private` path (exit 3). hive never runs it. The config is unchanged on any error. The first launcher added becomes `[defaults] launcher` when none is set. |
| `hive launchers default NAME` | Write `[defaults] launcher = NAME`. NAME is a registry or discover name (exit 2 otherwise). |
| `hive dirs [ROOT] [--depth N]` | Read-only: list the directories under the search roots. See [hive dirs](#hive-dirs). |
| `hive roots [add PATH \| remove PATH]` | Show `search_roots`, or add or remove one. See [hive roots](#hive-roots). |
| `hive inspect-launcher COMMAND` | Read-only: show a launcher's `CLAUDE_CONFIG_DIR` evidence. See [hive inspect-launcher](#hive-inspect-launcher). |
| `hive init` | Write the example config if none exists and print `wrote <path>; it has no agents yet, so 'hive up' starts only the queen; add agents with 'hive spawn DIR' or by editing it` (else print `<path> already exists`). Then print `config=<path> session=<session> socket=<socket>; set tmux_socket in the config to keep a test or isolated config off your real hive's tmux server`. The example defines no agents; the commented `[[agents]]` entry shows the keys. |
| `hive install-service [--enable]` | Write `~/.config/systemd/user/hive.service` and reload; `--enable` also runs `enable --now`. Without `--enable` it prints the follow-up commands `systemctl --user enable --now hive.service` and `loginctl enable-linger $USER`. Linux only (see [Run at login on macOS](service.md#run-at-login-on-macos)). Needs `systemctl` (else `systemctl not found`, exit 1) and a valid config. See [systemd service](service.md#systemd-service). |
| `hive uninstall-service` | Disable, remove the unit, reload. Prints `not installed: <path> does not exist` and exits 0 if there is no unit. Linux only, like `install-service`. |
| `hive --version` | Print `hive <version>`. |

## hive list

`hive list`

Config and running state as `key=value` lines, in this order: a header `session=... socket=... running=yes|no config=<path>`; the `queen` line; one `agent type=... dir=... count=... running=... command=... args=<json list>` line per type (with ` dir_missing=yes` when the dir is gone); one `pane name=<name> type=<type> id=<pane id>` line per running managed pane (with ` waiting=trust` when its screen shows the trust dialog); one `unmanaged pane=... window=... title=...` line per unmanaged pane; `drift start=<names|none> stop=<names|none>` when the session differs from the config; then `search_roots=<comma-separated>` and `discover=<command>`. The `queen` and `agent` lines carry `trusted=yes|no trust_file=<path>`.

## hive spawn

`hive spawn TARGET [-n N] [--type TYPE] [--command CMD | --launcher NAME] [--config-dir PATH] [--env KEY=VALUE ...] [--arg ARG ...] [--trust]`

Add N workers (default 1): raise `count` of the type TARGET names, or add an `[[agents]]` entry for a directory (absolute, `~/...`, or a name under `search_roots`), then reconcile. Prints `config agent=<type> count=<old>-><new> file=<path>`. `--command` must contain `{name}` and `--remote-control`. `--config-dir` writes `config_dir` into the new entry. `--launcher NAME` (`--sandbox` is an alias) copies `command` and `config_dir` from the launcher into the new `[[agents]]` entry; NAME is a `[[launchers]]` name or a `hive discover` record `name=NAME` (registry wins; error if unknown, or if `[queen] discover` is unset and NAME is not in the registry). A new type chosen with a launcher is `<base>-<NAME>` unless `--type` is given, base being TARGET's type or the directory's basename. `--launcher` cannot be combined with `--command` or `--config-dir`. Without `--command` or `--launcher`, a new type uses `[defaults] launcher` when set (type suffixed likewise), else `[defaults] command`. An existing type keeps its stored command and only gets a count bump. Spawn exits 2 when the resulting type already exists with a different `command`, `config_dir`, `args` or `--env` set (use a new `--type`; the same `args` list is accepted), and when the final type is reserved (e.g. dir `hive` with launcher `queen`). `--env` (repeatable) fills the new entry's `env` table. `--arg` (repeatable) fills its `args`; write `--arg=--fable` for a value starting with `-`. With `--launcher` (or the default launcher), args come from the discover record's optional `args` key, and any explicit `--arg` replaces them; `[[launchers]]` entries have no `args`. Exits 3 without changes if the directory is untrusted, unless `--trust` is given (see [Workspace trust](trust.md)). If the session is not running, only the config is updated.

## hive discover

`hive discover`

Run `[queen] discover` and print its output verbatim; the exit code is the command's. For `spawn --launcher`, each line is one record of whitespace-separated `key=value` tokens, values with spaces double-quoted (shlex): `name=api config_dir=~/.claude-api command="claude-supervisor run api -- -n {name} --remote-control {name}"`. Records are also usable as launcher names. `name`, `config_dir` and `command` are required; `args` is optional, a shell-quoted string split with shlex (`args="--fable"`, `args="--model 'x y'"`); unknown keys and blank lines are ignored; a bad line is an error naming it.

## hive dirs

`hive dirs [ROOT] [--depth N]`

Read-only: list the directories under each search root (or under ROOT: a search root, a directory inside one, or a name resolved as for `spawn`), N levels deep (default 1, max 3). Prints `root=<path>` per root (`root=<path> error=missing`, `error=not a directory` or the OS error if it cannot be read), then `dir=<path> name=<basename> type=<type>|none` per directory, `type` being the `[[agents]]` entry using that directory. A subdirectory that cannot be read prints `dir=<path> error=<reason>`. Skips hidden entries and `secrets`/`private` directories, lists a symlink only if it resolves inside `search_roots` and never descends into one; at most 500 records, then `more=yes`. A ROOT outside `search_roots` or under a `secrets`/`private` path is `refused: ...`, exit 3; unset `search_roots` exits 2; exit 1 if no root could be listed.

## hive roots

`hive roots [add PATH | remove PATH]`

Without arguments print `root=<path>` per search root (`roots=none` if unset). `add` appends an existing directory to `search_roots` in `config.toml` (written as `~/...` when PATH starts with `~`, else resolved) and prints `added <path>`, or `unchanged` if already present; refused (exit 3) under a `secrets`/`private` path. `remove` drops the entry naming that directory (`removed <path>`, or `not found: ...`, exit 2). Only rewrites a one-line `search_roots = [...]` (or inserts one) and keeps the rest of the file as is.

## hive inspect-launcher

`hive inspect-launcher COMMAND`

Read-only look at the launcher of a launch command (one argument, e.g. `"claude-supervisor run api -- -n {name}"`): resolves its first word on `PATH` and through symlinks, and reads it only if both paths are under `inspect_roots` and not under a `secrets`/`private` path (else `refused: ...`, exit 3; `not found: ...` for a missing, non-regular or unreadable file, exit 2). Prints `path=... resolved=... kind=binary`, or for a script `path=... resolved=... kind=script shebang=<first line> lines=<n>` (plus `truncated=yes` beyond 1 MiB); then for scripts the lines mentioning `CLAUDE_CONFIG_DIR`, `claude`, `exec`, `env`, `export`, `HOME=` or `XDG_CONFIG_HOME` as `line=N text=...` (secret-like lines as `line=N redacted=secret-like`), at most 200, then `more=yes`; and last `env CLAUDE_CONFIG_DIR=<value>|unset` from hive's own environment. Never runs the launcher.

Errors go to stderr as `hive: error: <message>`, warnings as `hive: warning: <message>`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | OK. Also `hive down` when the session is not running. |
| 1 | Runtime error (tmux or systemctl missing or failed, lock timeout, file not writable), or the session is not running (`status`, `attach`, `reconcile`). `hive dirs` when no root could be listed. |
| 2 | Usage or config error. Also `hive roots remove` with a path not in `search_roots`, and `inspect-launcher` `not found`. |
| 3 | Untrusted or refused: `spawn` of an untrusted directory without `--trust`, and `refused:` from `dirs`, `roots add` and `inspect-launcher`. |
| 130 | Interrupted (Ctrl-C). |

`hive discover` returns the discover command's exit code, `hive attach` returns tmux's, and `hive restart` through systemd returns `systemctl`'s.
