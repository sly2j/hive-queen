# Codex (system `codex`)

The `codex` system runs the Codex CLI (`codex`) as a worker in each pane. Workers are reachable from the Codex desktop app and the ChatGPT mobile apps through the machine's Codex remote-control daemon. Codex cannot run the queen in this release. See [Configuration](../configuration.md) for how `system` is set and resolved.

Verified on Codex CLI 0.164.0 (Linux). hive needs 0.164.0 or newer: `hive spawn` of a new Codex type exits 2 on an older `codex --version` and names the install command, `npm install -g @openai/codex`.

## One-time setup: pair the machine

Remote access runs through Codex's app-server daemon, one per `CODEX_HOME`. Pair it once, on the machine that runs the hive:

```sh
codex remote-control start   # start the daemon with remote control enabled
codex remote-control pair    # print a short-lived pairing code; enter it in the Codex app
```

hive never pairs and never types pairing codes. The pairing is stored under `~/.codex` and survives a daemon restart; after a reboot only `codex remote-control start` is needed, and hive runs that for you (next section). See the [Codex CLI command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli) for `codex remote-control`.

## The daemon

Before the first Codex pane of a `hive` run starts in the default `~/.codex`, hive checks for a running daemon (`~/.codex/app-server-daemon/daemon.pid` naming a live process):

- running with remote control (its command line has `--remote-control`, or, without `/proc`, `settings.json` there has `"remoteControlEnabled": true`): nothing to do;
- running without remote control (a plain daemon, as your own `codex` session starts one): hive warns that panes will not show in the app and leaves it alone; run `codex remote-control start` yourself;
- not running: hive runs `codex remote-control start` and warns if it fails; the pane starts either way.

hive never stops or restarts a daemon. Under `hive.service` (systemd) a daemon that `hive up` started belongs to the unit and stops with it; the next `hive up` starts it again.

## Default command

```
codex {args} -a never -s workspace-write
```

`-a never` (no approval prompts) and `-s workspace-write` (the sandbox may write the workspace) let the worker run unattended. `{args}` comes first, so a subcommand passed as args (such as `resume`) lands right after the binary. A command for this system needs no placeholder or token; `--remote-control` is a Claude flag and does not apply.

## No hooks, no session id

hive passes Codex no `-c` overrides and no hook flags, because either makes the TUI leave the shared daemon. On Codex 0.164.0 a pane launched with `-c hooks.<Event>=...` shows the startup warning "Running without the shared background server: command-line configuration overrides (-c, --enable, --disable, or --search) requires embedded mode", and `--dangerously-bypass-hook-trust` alone gives "Running without the shared background server: --dangerously-bypass-hook-trust requires embedded mode" (both seen in the warnings panel, F2). An embedded session is not on the paired daemon, so the app cannot see it. Remote access comes first, so Codex panes run without hive's status hooks:

- `hive list` and `hive status` show the tmux fallback for Codex panes (`source=tmux`: `busy`, `quiet` or `dead`); see [Idle detection](../idle-detection.md).
- Codex picks its own session id and hive cannot read it, so `@hive_session` is not set and `hive stop --keep-session` on a Codex instance exits 1 with "codex: session capture not supported in this release; use `codex resume` inside a new pane", changing nothing. To continue a conversation, attach (`hive attach`) to a Codex pane and use `/resume` there, or run `codex resume` in a terminal; both list the saved sessions. See [Resume](../resume.md).

## Config dir and trust

Leave `config_dir` unset: only the default `~/.codex` reaches the paired daemon. `CODEX_HOME` is rejected in `[env]`, per-type `env` and `--env`, and hive drops an inherited `CODEX_HOME` from the panes' environment. A worker with its own home sets it in the command and names the same dir as `config_dir`; such a pane gets no daemon handling and is not reachable from the app:

```toml
command = "sh -c 'CODEX_HOME=~/.config/hive/profiles/test/codex exec codex \"$@\" -a never -s workspace-write' sh {args}"
config_dir = "~/.config/hive/profiles/test/codex"
```

Codex asks "Trust this folder?" only inside a git work tree, keyed by the repository's top-level directory. hive reads `[projects."<root>"] trust_level` in `<CODEX_HOME>/config.toml`; a directory outside a git work tree counts as trusted. `hive spawn --trust` appends

```toml
[projects."/path/to/repo"]
trust_level = "trusted"
```

and re-reads the file to check it. hive never edits existing TOML: when a table for that root exists with another level, or the file does not parse, it refuses and names the file. A seeded entry suppresses the prompt (verified on 0.164.0). See [Workspace trust](../trust.md) for the `--trust` rules.

## Dialogs and `waiting=`

| Kind | Screen |
| --- | --- |
| `trust` | "Trust this folder?" in an untrusted git work tree. |
| `hooks_review` | "Hooks need review": hooks in your own Codex config that are new or changed and not yet trusted in `/hooks`. |
| `login` | Sign-in screen of a `CODEX_HOME` without credentials. |

Attach once (`hive attach`) to get through them; hive does not answer them for you.

## Names

Codex has no launch flag for a session name. The app titles a session from its first prompt; rename it with `/rename` in the pane. hive sets the tmux pane title to the pane name.

## Limitations

- No Codex queen in this release.
- Every launch in the default home creates a thread in the Codex app, test-profile launches included.
