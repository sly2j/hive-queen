# hive queen

hive queen runs Claude Code Remote Control sessions in tmux: N instances of each agent type, on a dedicated tmux server, with one extra coordinator session called the queen. You describe the agents in one config file; `hive up` starts them, and each one is then reachable by name from the Claude app or claude.ai through Remote Control. Use it to keep a fixed set of remote-controllable Claude sessions running on a machine, start them at login (systemd on Linux, a LaunchAgent on macOS), and add or remove instances by asking the queen.

The project is hive queen; the repository is `sly2j/claude-rc-hive` and the Python package is `hive`. The command, the config directory and the systemd unit are all named `hive`.

Terms used throughout are defined in [Concepts](docs/concepts.md).

## What it does

- Starts one tmux window per agent type and one pane per instance, all on its own tmux server (`tmux -L hive`), so other tmux sessions are never touched.
- Keeps the running session in line with `config.toml`: `hive up` on a running hive starts missing panes and stops surplus ones, without a restart.
- Starts the queen first: a Claude session that edits the config for you through `hive spawn` and `hive stop` ("one more X", "one less X").
- Checks Claude Code workspace trust before adding a directory. hive never seeds trust silently: it writes the trust key only when you pass `--trust`.
- Restricts the queen with Claude Code permission rules and a guard hook, so it can run single `hive` commands and touch files only in its own directory (see [Queen security model](docs/queen.md#queen-security-model)).
- On Linux, optionally installs a systemd user unit that starts the hive at login or boot. On macOS, a LaunchAgent recipe does the same (see [Run at login on macOS](docs/service.md#run-at-login-on-macos)).

## What it doesn't do

- It does not sandbox or isolate agents. Each pane runs its command as your user, in its directory. `--launcher NAME` (alias `--sandbox`) selects a launcher from `[[launchers]]` or `[queen] discover`; it is not an OS sandbox.
- It does not manage Claude login, accounts, or the Remote Control connection. The command in each pane does that.
- It does not know what a command does. An agent type is a directory plus a command; hive types the command into a shell and leaves it there. A command that exits is not restarted (the shell stays).
- It does not apply a changed `dir` or `command` to panes that are already running.
- It does not route work to agents or watch their output. The queen adds and removes workers; it does not do their work.
- It targets Linux and macOS with tmux. `hive install-service` needs systemd user units, so it is Linux-only.

## Quick start

You need Linux or macOS with git, tmux >= 3.0, uv (or pipx), and the Claude Code CLI (`claude`) logged in, with Remote Control; the queen's guard hook needs Claude Code >= 2.1.295. [Getting started](docs/getting-started.md) has the details, including the macOS setup.

```sh
uv tool install git+https://github.com/sly2j/claude-rc-hive
```

```sh
hive init                       # writes ~/.config/hive/config.toml; it defines no agents yet
hive spawn ~/work/my-project    # adds agent type my-project to the config
```

If Claude Code does not trust `~/work/my-project` yet, `hive spawn` prints `untrusted: ...` and exits 3 without changing anything; rerun it with `--trust` if you accept that (see [Workspace trust](docs/trust.md)).

```sh
hive up                         # starts the queen, then one pane per worker
hive attach                     # accept the queen's trust dialog, then detach with Ctrl-b d
```

In the Claude app or on claude.ai, open Remote Control: the worker appears as `my-project-myhost-1` and the queen as `hive-queen-myhost` (`myhost` being your short hostname). Ask the queen for "one more my-project" and it runs `hive spawn` for you.

```sh
hive status    # windows, panes, titles, running commands
hive list      # config and running state side by side
hive down      # stop everything
```

To start the hive at login, run `hive install-service --enable` on Linux, or follow [Run at login on macOS](docs/service.md#run-at-login-on-macos).

## Documentation

- [Getting started](docs/getting-started.md): prerequisites, install, the first hive step by step, uninstall.
- [Concepts](docs/concepts.md): the terms (agent type, worker, pane name, queen, trust root, launcher), how panes get their environment, the tmux socket, locking.
- [Configuration](docs/configuration.md): every key in `config.toml`, validation rules, placeholders, applying changes.
- [Commands](docs/commands.md): every `hive` command, its output and exit codes.
- [Queen](docs/queen.md): what the queen does and its security model.
- [Codex](docs/systems/codex.md): Codex CLI workers, the one-time remote-control pairing, trust and hooks.
- [Launchers](docs/launchers.md): named launch commands, such as a wrapper with its own Claude config dir.
- [Workspace trust](docs/trust.md): how hive checks and seeds Claude Code's folder trust.
- [Run at login](docs/service.md): the systemd user unit on Linux, a LaunchAgent on macOS.
- [Troubleshooting](docs/troubleshooting.md): symptoms and fixes.
- [Development](docs/development.md): clone, test, update an install, versioning.

## License

MIT. See `LICENSE`.
