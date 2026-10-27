# Concepts

## Terms

| Term | Meaning |
| --- | --- |
| agent type | One `[[agents]]` entry: a `type` name, a `dir`, a `count` (or explicit `indices`), a `system` and a `command`. One tmux window per type, named `<type>-<machine>`. (Called "agent kind" in `hive --help`.) |
| worker, instance | One running copy of an agent type, in one tmux pane. `hive spawn` adds workers, `hive stop` removes them. |
| pane name | `<type>-<machine>-<index>` (index from 1), or `hive-queen-<machine>`; `<machine>` is `prefix`. hive stores it in the tmux pane option `@hive_name`, sets it as the pane title, and the default command uses it as the Remote Control session name. |
| managed / unmanaged pane | A pane with `@hive_name` (or whose title equals a configured pane name, which hive then adopts) is managed. Every other pane in the session is unmanaged and never touched. |
| queen | A persistent agent session (Claude Code by default) in window `hive-queen-<machine>` that runs `hive` commands for you. `[queen] enabled = false` runs a hive without one. |
| system | The agent program a type runs: `claude` (Claude Code, the default) or `codex` (Codex CLI). Each has a driver that knows its default command, flags, trust file and dialogs; see [Claude](systems/claude.md) and [Codex](systems/codex.md). |
| hive config directory (hive dir, profile dir) | `${XDG_CONFIG_HOME:-~/.config}/hive`. Holds `config.toml`, the lock file `.lock`, the queen's directory `queen/`, `state/` (per-pane status files and kept session ids) and `profiles/`. |
| profile | A second, isolated hive on the same machine, with its own directory under `profiles/NAME/`, tmux server and systemd unit. Selected with `hive --profile NAME`; see [Test profile](test-profile.md). |
| node | Another machine's hive, listed in `[[nodes]]` and reached with `hive --node NAME ...` over ssh; see [Multi-node](multi-node.md). |
| state | What `hive list` and `hive status` report per pane: `busy`, `done`, `blocked`, `dead` or `quiet`, with its `source` and `age`; see [Idle detection](idle-detection.md). |
| kept session | The session id of a worker stopped with `hive stop --keep-session`, so `hive spawn --resume` can start it again into the same conversation; see [Resume](resume.md). |
| search root | A directory listed in `search_roots`. `hive spawn NAME` looks for a directory `NAME` under each one; `hive dirs` lists them. |
| trust root | The directory whose trust Claude Code records: the git toplevel of an agent's `dir`, else the `dir` itself. |
| trust file | The `.claude.json` that holds Claude Code's trust answers. See [Workspace trust](trust.md). |
| launcher | A named launch command, often a wrapper that runs Claude with its own Claude config dir. `[[launchers]]` and `[queen] discover` list them; `hive spawn --launcher NAME` uses one. See [Launchers](launchers.md). |
| `config_dir` | The config dir an agent's command uses (Claude's `CLAUDE_CONFIG_DIR`, Codex's `CODEX_HOME`). hive reads it only to find the trust file and never exports it. |

## Panes and environment

Panes are titled with the pane name and the app may not override it (`allow-set-title off`). Each pane runs a login shell (or tmux's `default-command` when `login_shell = false`), and the command is typed into it, so the shell stays after the command exits (the pane closes only when you `exit` that shell).

hive identifies its panes by the tmux pane option `@hive_name`, so the index in a pane name is hive's. tmux's own `pane_index` (shown by `hive status`) is positional and shifts when a pane is closed. A pane without `@hive_name` whose title equals a configured pane name is adopted (tagged) by `hive up` or `hive reconcile`.

When a pane starts, hive warns if a Claude command lacks `--remote-control` (the pane will not be reachable through Remote Control) or if the command's program is not on hive's `PATH` (the pane's login shell may have a different one). These are warnings only. For Claude panes, hive also appends a session id and the status hooks to the command; see [Claude](systems/claude.md) and [Idle detection](idle-detection.md).

Each pane runs one shell line: `export KEY="value"` for every `[env]` entry, then for the type's `env`, then `cd <dir>`, then the command. Values go inside double quotes in the pane shell: `\`, `"` and backticks are escaped and `$` is not, so `$VAR` expands and `$(cmd)` runs in the pane shell. `[env]` is also set on the hive tmux server (`set-environment -g`, with only `$VAR` expanded, by hive), so panes opened later inherit it. Use `[env]` for anything your login profile does not set.

Under the service, the tmux server starts with the bare systemd user environment, and a tmux pane can run a non-login shell (for example when tmux.conf sets `default-command`), which skips your profile (such as `~/.config/zsh/.zprofile`, where `SSH_AUTH_SOCK` for a systemd user ssh-agent is typically exported). That is why panes are login shells by default: they get the same environment as an SSH login, without hive knowing about ssh or anything else. Pairing the unit with `[service] after = ["ssh-agent.service"]` makes sure the agent socket exists before the panes start.

The tmux server inherits the environment of the `hive` call that starts it. hive drops the variables Claude Code sets for its child processes (`CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_SESSION_ID` and the like) from its tmux calls, so starting the hive from inside a Claude session does not make every agent think it is nested in it. It also drops `CLAUDE_CONFIG_DIR` and `CODEX_HOME`, so the panes do not load that session's config dir and settings (such as an `agent` setting whose tools lack Bash); each launch command picks its own. Anything else in that shell's environment still reaches the panes.

## tmux socket

hive uses its own tmux server (`tmux -L hive`, or the `tmux_socket` you set; a named profile uses `hive-NAME`). Plain `tmux ls` and `tmux attach -t myhost-agents` use the default socket and do not see it. Use `hive attach` or `tmux -L hive attach -t myhost-agents`. Your `~/.config/tmux/tmux.conf` still applies.

The reason: `hive down` and `systemctl --user stop hive` must never touch other tmux sessions.

## Locking

`up`, `down`, `spawn`, `stop`, `reconcile`, `roots` (also when only listing) and `launchers add|default` take a lock on `${XDG_CONFIG_HOME:-~/.config}/hive/.lock`, so the queen and you can run them at the same time. `restart` takes it only when it runs `down` and `up` itself; a restart through systemd takes it in the unit's `hive down` and `hive up`. A command waits up to 30 s for the lock, then exits 1 with `another hive command holds <path>; try again`. `hive down` still runs if the lock file cannot be opened, so systemd's `ExecStop` can always stop the session.
