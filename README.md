# hive queen

hive queen runs coding-agent sessions in tmux: N instances of each agent type, on a dedicated tmux server, with one extra coordinator session called the queen. You describe the agents in one config file; `hive up` starts them, and each one is then reachable from another device: a Claude Code session by name through Remote Control (the Claude app or claude.ai), a Codex CLI session through the machine's paired Codex daemon (the Codex app). Use it to keep a fixed set of remote-controllable agent sessions running on a machine, start them at login (systemd on Linux, a LaunchAgent on macOS), and add or remove instances by asking the queen.

The project is hive queen; the repository is `sly2j/claude-rc-hive` and the Python package is `hive`. The command, the config directory and the systemd unit are all named `hive`.

Terms used throughout are defined in [Concepts](docs/concepts.md).

## What it does

- Starts one tmux window per agent type and one pane per instance, all on its own tmux server (`tmux -L hive`), so other tmux sessions are never touched.
- Keeps the running session in line with `config.toml`: `hive up` on a running hive starts missing panes and stops surplus ones, without a restart.
- Starts the queen first: an agent session (Claude Code by default) that edits the config for you through `hive spawn` and `hive stop` ("one more X", "one less X").
- Runs two agent systems: Claude Code (the default) and Codex CLI (see [Codex](docs/systems/codex.md) for what differs). OpenCode and pi are deferred to the roadmap; OpenCode because its external-device relay (`opencode pair --remote`) could not be reached from another device.
- Shows, per pane, whether the agent is working, done or stuck (`hive list`, `hive status`), from Claude Code's own hook events where it can (see [Idle detection](docs/idle-detection.md)).
- Stops a worker without losing its conversation and brings it back later into the same session (`hive stop --keep-session`, `hive spawn --resume`; see [Resume](docs/resume.md)).
- Drives the hives on other machines over ssh (`hive --node NAME ...`; see [Multi-node](docs/multi-node.md)), and runs a second, isolated hive on the same machine for trying things out (`hive --profile NAME ...`; see [Test profile](docs/test-profile.md)).
- Checks Claude Code workspace trust before adding a directory. hive never seeds trust silently: it writes the trust key only when you pass `--trust`.
- Restricts the queen with Claude Code permission rules and a guard hook, so it can run single `hive` commands and touch files only in its own directory (see [Queen security model](docs/queen.md#queen-security-model)).
- On Linux, optionally installs a systemd user unit that starts the hive at login or boot. On macOS, a LaunchAgent recipe does the same (see [Run at login on macOS](docs/service.md#run-at-login-on-macos)).

## What it doesn't do

- It does not sandbox or isolate agents. Each pane runs its command as your user, in its directory. `--launcher NAME` (alias `--sandbox`) selects a launcher from `[[launchers]]` or `[queen] discover`; it is not an OS sandbox.
- It does not manage agent login, accounts, or the remote connection (Claude's Remote Control, Codex's pairing). The command in each pane, and the one-time setup on the per-system pages, do that.
- It does not know what a command does. An agent type is a directory plus a command; hive types the command into a shell and leaves it there. A command that exits is not restarted (the shell stays).
- It does not apply a changed `dir` or `command` to panes that are already running.
- It does not route work to agents or watch their output. The queen adds and removes workers; it does not do their work.
- It targets Linux and macOS with tmux. `hive install-service` needs systemd user units, so it is Linux-only.

## Quick start

You need Linux or macOS with git, tmux >= 3.0, uv (or pipx), and the Claude Code CLI (`claude`) logged in, with Remote Control; the queen's guard hook needs Claude Code >= 2.1.295. [Getting started](docs/getting-started.md) has the details, including the macOS setup and what comes after the first hive.

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

To start the hive at login, run `hive install-service --enable` on Linux, or follow [Run at login on macOS](docs/service.md#run-at-login-on-macos). To add Codex workers, pair the machine once and spawn with `--system codex` (see [Codex](docs/systems/codex.md)).

## Documentation

Start here:

- [Getting started](docs/getting-started.md): prerequisites, install, the first hive step by step, what to read next, uninstall.
- [Concepts](docs/concepts.md): the terms (agent type, worker, pane name, queen, system, profile, node, trust root, launcher), how panes get their environment, the tmux socket, locking.
- [Configuration](docs/configuration.md): every key in `config.toml`, validation rules, placeholders, applying changes.
- [Commands](docs/commands.md): the global options and every `hive` command, its output and exit codes.
- [Troubleshooting](docs/troubleshooting.md): symptoms and fixes.

Agent systems:

- [Claude](docs/systems/claude.md): the default command, session ids, wrappers, config dir and trust, first-run dialogs, resume.
- [Codex](docs/systems/codex.md): Codex CLI panes, the one-time remote-control pairing, the daemon, trust, and the limits of Codex panes.
- [Workspace trust](docs/trust.md): how hive checks and seeds Claude Code's folder trust.
- [Launchers](docs/launchers.md): named launch commands, such as a wrapper with its own config dir.

Operating a hive:

- [Queen](docs/queen.md): what the queen does and its security model.
- [Idle detection](docs/idle-detection.md): the `state=`, `source=` and `age=` fields, where they come from, and how to try them without an account.
- [Resume](docs/resume.md): stopping a worker with its session kept and starting it again into the same conversation.
- [Multi-node](docs/multi-node.md): running commands on the hives of other machines over ssh.
- [Test profile](docs/test-profile.md): a second, isolated hive on the same machine.
- [Run at login](docs/service.md): the systemd user unit on Linux, a LaunchAgent on macOS.
- [Development](docs/development.md): clone, test, module layout, update an install, versioning.

## License

MIT. See `LICENSE`.
