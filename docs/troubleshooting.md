# Troubleshooting

- **`tmux ls` shows nothing.** hive runs on its own tmux server. Use `hive attach`, `hive status`, or `tmux -L hive ls`.
- **`untrusted: ...` and exit 3 from `hive spawn`.** The directory's trust root is not trusted in the trust file shown. Confirm, then rerun with `--trust`. If the file shown is not the one your command's Claude uses, set `config_dir` (or `--config-dir`).
- **`hive: warning: untrusted <name> ...` from `hive up`, or `waiting=trust` in `hive list`.** The pane shows Claude's trust dialog. `hive attach` and accept it.
- **`skipped <name>: dir <dir> does not exist`.** The type's `dir` is gone. Fix the path in `config.toml`, or `hive stop <type>` until its count is 0.
- **`'<program>' not found in PATH` warning, or a pane shows `command not found`.** The command's program is not on the pane's `PATH`. Under the service, panes get the login shell's `PATH`; check that your profile adds the directory (for example `~/.local/bin`).
- **An agent does not appear in Remote Control.** Check that its command contains `--remote-control {name}`, then `hive attach` and look at the pane: Claude may be waiting at a trust dialog or a login prompt.
- **`another hive command holds <path>; try again`.** Another `hive` command (possibly the queen's) is running. Retry when it finishes.
- **A broken `config.toml`.** Most commands exit 2 naming the file and key. `hive down` and `hive status` still work, with a `config problem: ...` warning, using `prefix`, `session` and `tmux_socket` from the config's parsable top-level lines or the defaults. If one of those names is set but invalid, they exit 2 too; fix it first.
- **`config edit produced an unexpected result`.** hive's line editor cannot safely rewrite this config (for example a `count =` line inside a multi-line string). Edit `config.toml` by hand.
- **The queen still follows old instructions after an upgrade.** Its files re-sync only when the queen starts; run `hive restart`.
