# Run at login

## systemd service

Linux only. On macOS, `hive install-service` and `uninstall-service` exit 1 (systemd services are Linux-only); see [Run at login on macOS](#run-at-login-on-macos).

`hive install-service --enable` writes `~/.config/systemd/user/hive.service`, reloads systemd and starts the unit; it then starts at login (at boot only with `loginctl enable-linger $USER`). Without `--enable` it writes and reloads only, and prints those two commands (`systemctl --user enable --now hive.service`, `loginctl enable-linger $USER`). It checks for `systemctl` first and exits 1 with `systemctl not found` if it is missing. The unit always goes to `~/.config/systemd/user`, where the systemd user manager looks. If `XDG_CONFIG_HOME` is set to something other than `~/.config` when you install, the unit gets an `Environment=XDG_CONFIG_HOME=...` line, so the service reads the same config as your shell.

`ExecStart` and `ExecStop` use `%h/.local/bin/hive`, or the `hive` found on `PATH` if it is elsewhere. `After=` is `network-online.target` plus the units in `[service] after`. With the defaults the unit is:

```ini
[Unit]
Description=hive: agent sessions in tmux
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/.local/bin/hive up
ExecStop=%h/.local/bin/hive down
# The tmux server forked by `hive up` stays in this cgroup while the unit is
# active. tmux may move pane processes into their own tmux-spawn-*.scope units;
# `hive down` ends them by killing the session.
KillMode=control-group

[Install]
WantedBy=default.target
```

`hive up` forks the tmux server, which stays in the unit's cgroup while the unit is active. Once the service is installed, restart with `systemctl --user restart hive` (what `hive restart` does). A plain `hive down && hive up` would start a new tmux server outside the unit's cgroup, so `systemctl --user status hive` would not show it, and the cgroup kill would no longer back up `ExecStop`.

`KillMode=control-group` is the default, kept explicit. tmux built with systemd support (Debian's 3.5a is) moves each pane's processes into its own `tmux-spawn-*.scope` unit. `systemctl --user status hive` then lists only the tmux server, and the cgroup kill does not reach the agents; they end when `ExecStop` (`hive down`) kills the session and the panes get SIGHUP. `hive down` alone leaves the unit "active" (`RemainAfterExit`).

Logs: `journalctl --user -u hive`, or `journalctl --user-unit hive` where journald keeps no per-user files (`Storage=volatile`).

## Run at login on macOS

There is no `hive install-service` on macOS. Write a LaunchAgent by hand, `~/Library/LaunchAgents/local.hive.plist`. Use the absolute path of `hive` (`command -v hive`) and write out your home directory: launchd does not expand `~`. No `KeepAlive`: `hive up` exits once the tmux session is started.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.hive</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/.local/bin/hive</string>
    <string>up</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/Users/YOU/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/YOU/Library/Logs/hive.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOU/Library/Logs/hive.log</string>
</dict>
</plist>
```

Load it with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.hive.plist` (it also runs at each login), and unload it with `launchctl bootout gui/$(id -u)/local.hive`. Unloading does not stop the hive; run `hive down` for that. On macOS `hive restart` just runs `hive down` and `hive up`.
