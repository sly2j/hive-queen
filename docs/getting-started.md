# Getting started

## Prerequisites

- Linux or macOS, with git.
- tmux >= 3.0 (tested with 3.2a and 3.5a).
- uv (or pipx) to install hive. `uv tool install` provides Python >= 3.11 itself; with pipx you need Python >= 3.11 already.
- Claude Code CLI (`claude`), logged in, with Remote Control. The queen's guard hook needs Claude Code >= 2.1.295 (for the hook's `onFailure` setting). The hook runs with hive's own Python interpreter, so `python3` need not be on `PATH`.
- Optional: Codex CLI (`codex`) >= 0.164.0, signed in, for Codex workers. The machine is paired with the Codex app once; see [Codex](systems/codex.md).
- Optional: systemd (user units) on Linux to start the hive at login. On macOS, use a LaunchAgent.

## Install

On macOS, install the prerequisites with Homebrew first, and make sure `PATH` includes `~/.local/bin` (where uv puts `hive`) and `/opt/homebrew/bin` (tmux, uv):

```sh
brew install tmux uv
```

```sh
uv tool install git+https://github.com/sly2j/claude-rc-hive
# or, from a checkout:   uv tool install .
# or with pipx:          pipx install git+https://github.com/sly2j/claude-rc-hive
```

On distributions that follow PEP 668 (for example Debian 13) and on Homebrew Python, `pip install --user` is blocked; use uv or pipx.

## First hive

1. Write the config:

   ```sh
   hive init
   ```

   This creates `~/.config/hive/config.toml` (or under `$XDG_CONFIG_HOME`). It defines no agents; the default command for agents is `claude -n {name} --remote-control {name} --permission-mode auto --session-id {session_id}`. Every key is described in [Configuration](configuration.md).

2. Add an agent type for a project directory:

   ```sh
   hive spawn ~/work/my-project
   ```

   If Claude Code does not trust that directory yet, hive prints `untrusted: ...` and exits 3 without changing anything. Trusting a folder enables its `.claude/settings.json` allow rules, hooks and env. If you accept that, rerun with `--trust`:

   ```sh
   hive spawn ~/work/my-project --trust
   ```

   The session is not running yet, so this only adds an `[[agents]]` entry with type `my-project`.

3. Start the hive:

   ```sh
   hive up
   ```

   It starts the queen, then one pane per worker, and prints a `started <name>` line for each.

4. Accept the queen's trust dialog. On first start Claude Code asks whether to trust the queen's directory, and `hive up` warns `untrusted hive-queen-<machine> ...`. Attach, accept the dialog in the queen's pane, and detach with the tmux prefix followed by `d` (`Ctrl-b d` by default):

   ```sh
   hive attach
   ```

5. Connect. In the Claude app or on claude.ai, open Remote Control; each agent appears under its pane name, for example `my-project-myhost-1`, and the queen as `hive-queen-myhost` (`myhost` being the short hostname, the default prefix).

6. Check state:

   ```sh
   hive status   # windows, panes, titles, running commands
   hive list     # config and running state side by side
   ```

   Both show, per pane, whether its agent is `busy`, `done`, `blocked` or `dead` (see [Idle detection](idle-detection.md)).

7. Stop everything:

   ```sh
   hive down
   ```

To start the hive at login, run `hive install-service --enable` on Linux (see [systemd service](service.md#systemd-service)), or follow [Run at login on macOS](service.md#run-at-login-on-macos).

## Next steps

- Ask the queen. From the Remote Control session `hive-queen-myhost`, "one more my-project" runs `hive spawn` for you; [Queen](queen.md) says what it may and may not do.
- Add Codex workers: pair the machine once, then `hive spawn ~/work/other --system codex`. [Codex](systems/codex.md) has the setup and the limits of Codex panes.
- Keep a worker's conversation across a stop: `hive stop my-project --index 1 --keep-session`, later `hive spawn my-project --resume my-project-myhost-1` ([Resume](resume.md)).
- Run hive commands on another machine's hive with `hive --node NAME ...` ([Multi-node](multi-node.md)), or try things in a second, isolated hive with `hive --profile test ...` ([Test profile](test-profile.md)).
- Something looks wrong: [Troubleshooting](troubleshooting.md).

## Uninstall

```sh
hive down
hive uninstall-service           # if you installed it
uv tool uninstall hive           # or: pipx uninstall hive
rm -r ~/.config/hive             # config.toml, .lock, queen/, state/ and profiles/ (or under $XDG_CONFIG_HOME)
```

Trust keys that `hive spawn --trust` wrote stay in Claude Code's trust file (and in Codex's `config.toml`), and a Codex pairing stays under `~/.codex`.
