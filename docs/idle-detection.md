# Idle detection

`hive list` and `hive status` show, for every running pane, whether its agent is working, has
finished its turn, or is stuck. The queen reads the same fields to decide which workers can take
new work or be stopped, since an open session that only waits still holds a pane and can cost
tokens when prompted again.

```
pane name=api-mybox-1 type=api id=%3 system=claude state=done source=hook age=42
```

`hive status` appends `state=... source=... age=...` to the line of every pane hive manages.
The fields are advisory: they report what the agent last said or what the screen looks like, not
a guarantee.

## States and sources

| state | meaning |
|---|---|
| `busy` | working on a turn (or the screen is still changing) |
| `done` | finished its turn and waits for the next prompt |
| `blocked` | waits for a person: a permission prompt, a question, or an API error such as a rate limit |
| `dead` | the agent exited and the pane is back at its shell |
| `quiet` | screen unchanged for 30 seconds or more: idle or blocked, the tmux fallback cannot tell which |

`source` says where the state comes from, and `age` is the number of seconds since then:

- `hook`: the agent's own lifecycle events, written by hive's hook script to the pane's status
  file. `age` is the time since the last event.
- `api`: the system's own server, polled when `hive list` runs (no current driver uses it yet).
  `age` is 0.
- `tmux`: no status file exists, so hive looks at the pane. A shell as the pane's current
  command (`sh`, `bash`, `zsh`, `fish`, `dash`, `ksh`, or the basename of `pane_shell`) gives
  `dead`; a screen unchanged for 30 seconds gives `quiet`; anything else gives `busy`. `age` is
  the time since the screen last changed. This source never reports `done`.
  In the first moment after a pane starts, before its shell has run the typed command, the
  shell is the current command, so a `list` at that instant can show `dead`.

`waiting=<kind>` stays a separate field: a pane showing a dialog (trust, theme, login) is `busy`
or `quiet`, and the kind says why.

Codex panes always report the tmux fallback: hive passes Codex no hooks, because they would take
the pane off the shared daemon that the Codex app reaches (see
[Codex](systems/codex.md#no-hooks-no-session-id)).

## Files

Each profile keeps the state under its profile dir (`~/.config/hive/` for the default profile,
`~/.config/hive/profiles/<name>/` for a named one):

```
state/status/<pane name>.json   written by the hook script on every event
state/screens/<pane name>.json  the tmux fallback's screen hash and the time it last changed
```

A status file holds `{"state", "event", "session_id", "ts", "detail"}`: the state, the agent's
event name, the agent's session id, the epoch time of the event, and the notification type, start
source, error type or end reason when the event has one. Both files of a pane are deleted when
hive starts the pane, so a new launch never shows the previous launch's state. `config.toml`
stays the only desired state; these files are observations.

## Claude Code

Every launch with a session id (each `hive up`, `reconcile` and `spawn`) appends
`--settings '<json>'` to the command, after the session flags. The JSON registers one hook per
event, each running `<hive's python> <hive>/hooks/status_hook.py <status file> --event <name>`.
The hook only adds entries; settings from the user's and the project's files still apply.

| Claude event | state | detail |
|---|---|---|
| `SessionStart` | `done` | `source` (`startup`, `resume`, ...) |
| `UserPromptSubmit` | `busy` | |
| `Stop` | `done`, or `busy` while background tasks or session crons are pending | |
| `StopFailure` | `blocked` | `error` (`rate_limit`, ...) |
| `Notification` `permission_prompt`, `agent_needs_input` | `blocked` | notification type |
| `Notification` `idle_prompt` | `done` | notification type |
| `SessionEnd` | `dead` | `reason` |

Event names and fields follow the [Claude Code hooks reference](https://code.claude.com/docs/en/hooks).
`Stop` does not fire when the user interrupts a turn, so an interrupted pane stays `busy` until
its next event (Claude's `idle_prompt` notification follows after about a minute of idle input).
The hook script always exits 0 and prints nothing, so it can never keep Claude from stopping.

### Wrapper commands

Appended flags reach Claude only when the command passes them on. A `sh -c` wrapper takes them as
its own positional parameters, so forward them with `"$@"` and a placeholder `$0`:

```
sh -c 'CLAUDE_CONFIG_DIR=$HOME/.claude-work exec claude -n {name} --remote-control {name} "$@"' sh
```

Use `exec` too: without it the pane's current command is `sh` while Claude runs, which the tmux
fallback reads as `dead` (the hook path is not affected).

## Trying it without an account

`tests/data/fake_worker.py` stands in for Claude: it reads the appended `--session-id` and
`--settings`, runs the hook commands with Claude-shaped input, then sleeps. In a test profile
(see [Test profile](test-profile.md)):

```
uv run hive --profile test spawn ~/some/dir --type fake --trust \
    --command "python3 $PWD/tests/data/fake_worker.py {name} --remote-control" \
    --config-dir ~/.config/hive/profiles/test/claude
uv run hive --profile test up && uv run hive --profile test list
```

The default event sequence is `SessionStart` at once, `UserPromptSubmit` after 3 seconds and
`Stop` after 6, so `list` shows `done`, then `busy`, then `done`. Set `FAKE_EVENTS` in the type's
env to change it, for example `FAKE_EVENTS="SessionStart Notification:permission_prompt:2"` for
`blocked` (items are `Event`, `Event:SECONDS` or `Notification:TYPE:SECONDS`, seconds counted
from the start). A command that ignores the appended flags, such as
`sh -c 'echo {name} --remote-control; exec sleep 1d'`, writes no status file and shows the tmux
fallback: `busy`, then `quiet` after 30 seconds, and `dead` after Ctrl-C.
