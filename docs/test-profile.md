# Test profile

A named profile is a second, isolated hive on the same machine. Use one to try hive commands
without touching your real hive, for example from an agent that itself runs inside the real hive.

Select it with the global option `--profile NAME` or with `HIVE_PROFILE=NAME`; the option wins.
`NAME` matches `[a-z0-9][a-z0-9-]*`, and `default` means the default profile.

| | default profile | profile `NAME` |
|---|---|---|
| config | `~/.config/hive/config.toml` | `~/.config/hive/profiles/NAME/config.toml` |
| lock, queen dir | `~/.config/hive/.lock`, `.../hive/queen` | `.../profiles/NAME/.lock`, `.../profiles/NAME/queen` |
| `prefix` default | short hostname | `NAME` |
| `session` default | `<prefix>-agents` | `<prefix>-agents` |
| `tmux_socket` default | `hive` | `hive-NAME` |
| systemd unit | `hive.service` | `hive-NAME.service` |

(`~/.config` stands for `$XDG_CONFIG_HOME` when set.)

Safety rules:
- A named profile refuses the socket `hive` and the default profile's socket (exit 2), also in
  `down` and `status` with a broken config, so it cannot reach the real hive's tmux server.
- `restart`, `install-service` and `uninstall-service` only use `hive-NAME.service`; the unit runs
  `hive --profile NAME up` and `hive --profile NAME down`.
- Every pane of the profile exports `HIVE_PROFILE=NAME`, so plain `hive` commands typed in it
  address the same profile.

## A queen-less hive with fake workers

`[queen] enabled = false` starts no queen (and stops a running one). `hive up` with no queen and
no agents prints `nothing to start: queen disabled and no agents` and exits 0 without a session.
`spawn` only edits the config while the session is down, so spawn first, then `up`.

A fake worker needs no Claude account and keeps trust seeding inside the profile:

```
uv run hive --profile test init
# edit ~/.config/hive/profiles/test/config.toml:
#   [defaults]
#   command = "sh -c 'echo {name} --remote-control; exec sleep 1d'"
#   [queen]
#   enabled = false
uv run hive --profile test spawn ~/some/dir --trust -n 2 \
    --config-dir ~/.config/hive/profiles/test/claude
uv run hive --profile test up
uv run hive --profile test list
uv run hive --profile test stop dir -n 1
uv run hive --profile test down    # kills only the hive-test server
```

`--config-dir` points the trust check (and `--trust`) at a file under the profile, so
`~/.claude.json` is never written.
