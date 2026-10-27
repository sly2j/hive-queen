# Claude (system `claude`)

The `claude` system runs Claude Code in each pane. It is the only system in this release and the default. See [Configuration](../configuration.md) for how `system` is set and resolved.

## Default command

```
claude -n {name} --remote-control {name} --permission-mode auto --session-id {session_id}
```

Verified on Claude Code 2.1.311; Claude has no minimum version, so `hive spawn` does not probe it.

A command for this system must contain `{name}` and `--remote-control`; `[[launchers]]`, `hive spawn --command` and `hive launchers add` reject one without them (exit 2).

## Session id

Every pane launch gets a fresh UUID. A command containing `{session_id}` has it substituted (also inside `args`). Otherwise hive appends `--session-id <uuid>` at the end of the command. hive stores the id as the tmux pane option `@hive_session`:

```sh
tmux -L <socket> show-options -p -t <pane> @hive_session
```

The same id appears as `--session-id <uuid>` in the pane process's arguments (`ps -o args=`).

### Wrappers

A launcher or wrapper must pass flags it does not know through to `claude`, because the appended `--session-id` goes to the wrapper first. A `sh -c '...'` command must carry `{session_id}` inside the quotes; an appended flag would become the shell's `$0`:

```toml
command = "sh -c 'CLAUDE_CONFIG_DIR=~/.claude-x exec claude -n {name} --remote-control {name} --session-id {session_id}'"
```

## Config dir and trust

`config_dir` (on `[queen]`, `[[agents]]` and `[[launchers]]`) names the Claude config dir the command uses. hive only reads `<config_dir>/.claude.json` to check workspace trust; it never exports it. `CLAUDE_CONFIG_DIR` is rejected in `[env]`, per-type `env` and `--env`; set it inside the launcher command instead and give hive the same path as `config_dir`. See [Workspace trust](../trust.md).

## Dialogs and `waiting=`

`hive list` adds ` waiting=<kind>` to a pane line when the pane's screen shows a dialog that blocks the session:

| Kind | Screen |
| --- | --- |
| `trust` | Workspace trust dialog. |
| `theme` | First-run text-style screen of a fresh config dir. |
| `login` | Login method screen. |
| `rc_consent` | Remote Control consent. The phrase comes from Claude's documentation and is not verified against a live session. |

A fresh config dir shows `theme`, then `login`; trust and Remote Control consent come after login. Attach once per config dir (`hive attach`) to get through them. hive does not answer these dialogs for you.
