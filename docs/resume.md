# Resume

A worker stopped with `--keep-session` can be started again later into the same conversation:

```sh
hive stop notes --index 1 --keep-session
# config agent=notes count=2->1 indices=2 file=...
# kept session name=notes-mybox-1 session=0b6f3c1e-...; resume with: hive spawn notes --resume notes-mybox-1
# stopped notes-mybox-1

hive spawn notes --resume notes-mybox-1
# config agent=notes count=1->2 file=...
# resume name=notes-mybox-1 session=0b6f3c1e-...
# started notes-mybox-1  [...]  claude -n notes-mybox-1 --remote-control notes-mybox-1
```

The resumed pane gets its old name and number back, and its agent continues the conversation it
had when it was stopped.

## Keeping a session

`hive stop ... --keep-session` takes every form of `hive stop` (`TYPE -n N`, `TYPE --index N`,
instance names). Before the panes go, it reads each removed instance's session id:

1. the `session_id` in the pane's status file, written by the status hooks (see
   [Idle detection](idle-detection.md)), so a session the agent replaced (Claude's `/clear`) is
   followed;
2. else the `@hive_session` pane option hive sets at launch, so a pane whose hooks never ran (for
   example one still at a first-run dialog) is kept too.

When an instance has neither (the pane is not running and left no status file), stop exits 1 and
changes nothing. The ids go to `<profile dir>/state/sessions.json`, one entry per instance name;
the config stays the only record of which workers should run. A plain `hive stop`, without
`--keep-session`, forgets the kept id of each instance it removes.

`hive list` prints one line per kept session:

```
kept name=notes-mybox-1 session=0b6f3c1e-... resume=no
```

## Resuming

`hive spawn TYPE --resume NAME` puts instance NAME of TYPE back into the config, marks its kept
session (`resume=pending` in `hive list`) and reconciles. The next launch of NAME runs the type's
command as configured, with the driver's resume flags placed like `args` (at `{args}`, else
appended): Claude gets `--resume <id>`. The session flags are left out, because Claude refuses
`--session-id` together with `--resume`: hive appends no `--session-id`, and drops
`--session-id {session_id}` (also with `=` or a quoted id) from the command and its args. The
status hooks are passed as on every launch, the pane's status file starts empty, and
`@hive_session` holds the resumed id. The launch uses the kept entry up; a later launch of the same
name starts a new session.

If the session is not running, only the config and the mark are written, and the next `hive up`
resumes the instance.

Exit 2, with the config unchanged, when NAME has no kept session, NAME is not an instance of TYPE,
the instance is configured already (stop it first), or `--resume` is combined with another spawn
option than `--trust` (`-n`, `--type`, `--command`, `--arg`, `--config-dir`, `--launcher`,
`--system`, `--env`).

## Limits

- Codex: hive cannot read a Codex session id, so `hive stop --keep-session` on a Codex instance
  exits 1 and changes nothing. Continue a Codex conversation by hand, with `/resume` in a pane or
  `codex resume` in a terminal; see [Codex](systems/codex.md#no-hooks-no-session-id).
- Claude resumes a conversation it has a transcript of; a session that never got a prompt has
  none, and Claude reports that in the pane.
- A wrapper that puts the session id in another form than `--session-id {session_id}` must not
  pass it on resume itself; see [Claude: Wrappers](systems/claude.md#wrappers).
