# Multi-node

One hive can control the hives on other machines over ssh. Each machine runs its own hive (its
own config, lock and tmux server); the controlling hive only forwards commands. A remote machine
is a node: an entry in `[[nodes]]` of the controlling hive's `config.toml`.

```toml
[[nodes]]
name = "swarm"                        # used as hive --node swarm
host = "swarm"                        # ssh destination: an ~/.ssh/config alias or user@host
hive = "/home/me/.local/bin/hive"     # remote hive executable (default: hive)
profile = "test"                      # optional remote profile (default: the remote default profile)
description = "Raspberry Pi"          # optional
```

Keys: see [Configuration](configuration.md). `hive nodes` lists the entries, one
`node name=... host=... hive=... profile=...` record per line. Nodes are added by editing the
config; there is no command for it.

## Running a command on a node

```
hive --node swarm list
hive --node swarm spawn api -n 2
hive --node swarm stop api --index 2
```

`hive --node NAME COMMAND ...` runs

```
ssh -o BatchMode=yes -o ConnectTimeout=10 HOST -- 'HIVE [--profile PROFILE] COMMAND ...'
```

with stdin closed and stdout and stderr passed through. The remote exit code is hive's exit code,
except ssh's own failure code 255, which becomes exit 1 with `node NAME unreachable`. `--node`
must come before the subcommand, and the remote command may not start with an option other than
`--version`, `-h` or `--help` (the remote profile comes only from the entry). `hive --node NAME
attach` is refused (exit 2): attaching needs a terminal, so run `ssh -t HOST hive attach` yourself.
The local config is not validated for `--node`; only its `[[nodes]]` table is read.

## Setting up a node

1. Install hive on the node and write its config (`hive init`).
2. Make ssh non-interactive: key authentication, and the host key accepted once by hand
   (`ssh HOST true`). `BatchMode=yes` never prompts, so an unknown host key or a password prompt
   shows up as `node NAME unreachable`.
3. Set `hive` to the full path of the remote executable. ssh runs the command through the remote
   login shell without a login profile, and a non-interactive bash usually has no `~/.local/bin`
   on its `PATH`; zsh reads `~/.zshenv`, bash does not.
4. A node that the controlling hive's queen manages needs no queen of its own: set
   `[queen] enabled = false` in the node's config. A node that has its own queen keeps it; both
   queens then manage the same workers, which works but is confusing.

## Profiles and safety

From a named local profile (a [test profile](test-profile.md)), a node must set `profile` to a
named remote profile, not `default`; otherwise the command is refused with exit 2. A test hive
therefore never drives a remote production hive. From the default profile any node may be used.
Without `profile`, or with `profile = "default"`, no `--profile` option is sent, so a remote hive
older than profiles works as a node.

## The queen

The queen may run `hive nodes` and `hive --node NAME COMMAND ...`. Its guard checks the remote
command with the same rules as a local one: `down`, `restart`, `roots add`, `launchers add` and
`spawn --trust`, `--env` and unknown `--command`/`--arg` ask the user first (spawn values are
compared with the local `config.toml`), and any option other than `--node NAME` before the
subcommand is blocked.
