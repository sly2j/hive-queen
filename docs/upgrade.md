# Upgrade to 2.0

hive queen 2.0 is the first tagged release (`v2.0`). The command is still `hive`, and the config file, the config directory and the systemd unit keep their names. What changes for an install is the repository and the Python distribution name.

## What is new in 2.0

- Agent systems: Claude Code (the default) and Codex CLI, chosen per queen, agent type or launcher with the `system` key ([Claude](systems/claude.md), [Codex](systems/codex.md)).
- Per-instance stop: `hive stop TYPE --index N` removes one instance and keeps the others running ([Commands](commands.md#hive-stop)).
- Done and idle detection: `hive list` and `hive status` show `state=` per pane ([Idle detection](idle-detection.md)).
- Session resume: `hive stop --keep-session`, then `hive spawn TYPE --resume NAME` ([Resume](resume.md)).
- Multi-node control over ssh: `hive --node NAME ...` ([Multi-node](multi-node.md)).
- Named profiles for a second, isolated hive: `hive --profile NAME ...` ([Test profile](test-profile.md)).
- `[queen] enabled = false` runs a hive without a queen ([Configuration](configuration.md)).

## Where the repository moved

The repository is now `sly2j/hive-queen` (formerly `sly2j/claude-rc-hive`). GitHub redirects the old URL to the new one, for the web pages and for `git` clone, fetch and push, so existing clones keep working. Point a clone at the new name anyway:

```sh
git remote set-url origin git@github.com:sly2j/hive-queen.git
# or: git remote set-url origin https://github.com/sly2j/hive-queen
```

## Upgrading an install from 1.x

The Python distribution was `hive` and is now `hive-queen`, so `uv tool upgrade` cannot move from one to the other. Uninstall the old one, then install the new one:

```sh
uv tool uninstall hive
uv tool install git+https://github.com/sly2j/hive-queen
hive --version                   # hive 2.0
```

With pipx: `pipx uninstall hive`, then `pipx install git+https://github.com/sly2j/hive-queen`. Later upgrades use the new name: `uv tool upgrade hive-queen`.

The command is still `hive` in `~/.local/bin`. A running hive keeps running during the swap, but the queen's guard hook runs the Python of the install that started it, which the uninstall removed: until the restart, a Claude queen's tool calls are blocked. Restart right after installing, so the queen starts from the new release's queen files (instructions, permission rules, guard hook) and every pane gets the new launch flags:

```sh
hive restart
```

Under the systemd unit, `hive restart` restarts `hive.service`.

## What changes for existing configs

`~/.config/hive/config.toml` stays where it is and needs no edits. After the restart:

- Claude panes get a session id: a command without `{session_id}` gets `--session-id <uuid>` appended at its end, and every Claude launch also gets `--settings '<json>'` with hive's status hooks. A wrapper or launcher command must pass flags it does not know through to `claude`; see [Claude: Wrappers](systems/claude.md#wrappers). Put `{session_id}` in a command to place the id yourself.
- `system` is a new optional key on `[defaults]`, `[queen]`, `[[agents]]` and `[[launchers]]`. It defaults to `claude`, so a 1.x config runs exactly as before.
- `hive stop TYPE` still removes N instances, highest indices first (default 1). New: `--index N` stops exactly those instances, and `--keep-session` records their session ids for `spawn --resume`. A type whose instances are no longer `1..count` gets an `indices` key in the config.
- `[queen] enabled` is new and defaults to `true`: the queen starts as before.
- Profiles: the default profile is the 1.x layout, `~/.config/hive/`. Named profiles live under `~/.config/hive/profiles/<name>/` and never touch the default profile's config, tmux server or unit.
- State: hive now writes `~/.config/hive/state/` (pane status files, screen hashes, and `sessions.json` for kept sessions). It holds no configuration; deleting it loses only the kept sessions.

## Codex

Codex is new in 2.0, so a 1.x config has no Codex panes. Before adding one, pair the Codex daemon once and read [Codex](systems/codex.md): hive starts the remote-control daemon for the first Codex pane when none is running, never stops it, and seeds Codex folder trust only with `--trust`.

A Codex queen (`[queen] system = "codex"`) needs its folder and guard hook approved once in the pane. Codex records the hook's approval against the hook entry, which contains the Python path of the hive install. Reinstalling as `hive-queen` moves that path (uv keeps each tool in a directory named after its distribution), so after the upgrade the queen shows "Hooks need review" again: run `hive attach` and choose "Trust all and continue". See [The Codex queen: Upgrading](systems/codex.md#upgrading).

## Run at login

The systemd unit is unchanged for the default profile: `~/.config/systemd/user/hive.service` runs `%h/.local/bin/hive`, which the new install provides under the same name. There is no need to reinstall it. A named profile gets its own unit, `hive-NAME.service` ([Run at login](service.md)).
