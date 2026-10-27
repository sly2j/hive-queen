"""The session: up, down, restart, status, attach, and reconcile with the config."""

import os
import subprocess
import sys
from pathlib import Path

from hive import tmux
from hive.launch import expand_pane, preflight, warn_untrusted
from hive.lock import hold_lock
from hive.queen import materialize_queen
from hive.reconcile import desired_panes, plan, queen_name
from hive.service import systemd_unit_active, unit_name
from hive.util import die, warn

BROKEN_CONFIG_NOTE = (
    "Works with a broken config.toml: prefix, session and tmux_socket are read from its "
    "parsable top-level lines, and only names the config does not set fall back to the "
    "defaults. A name that is set but invalid or unparsable exits 2 instead of guessing.")


def kept_queen(cfg):
    """The queen's name when it is enabled (reconcile never stops it), else None."""
    return queen_name(cfg["prefix"]) if cfg["queen"]["enabled"] else None


def reconcile(cfg, dry_run=False, announce_idle=True):
    """Make the running session match the config: adopt, start, then stop."""
    session = cfg["session"]
    if not tmux.session_running(cfg):
        die(f"session {session} not running; run 'hive up'", 1)
    queen = queen_name(cfg["prefix"])
    running, _ = tmux.running_panes(cfg)
    wanted = desired_panes(cfg)
    to_start, to_stop = plan(wanted, running, kept_queen(cfg))
    windows_of = {p.name: p.window for p in wanted}
    adopted = [r for r in running.values() if r.adopted]
    acted = False

    if not dry_run:
        # Cheap; panes opened later inherit it.
        for key, value in cfg["env"].items():
            tmux.tmux(cfg, "set-environment", "-g", key, os.path.expandvars(value))
    # Adoption only retags a running pane, so --dry-run does not report it.
    for r in adopted if not dry_run else []:
        tmux.tmux(cfg, "set-option", "-p", "-t", r.pane_id, "@hive_name", r.name)
        tmux.tmux(cfg, "select-pane", "-t", r.pane_id, "-T", r.name)
        # A legacy window (<prefix>-<type>, <prefix>-queen) is renamed so new panes split into it.
        legacy_window = f"{cfg['prefix']}-{r.type}"
        if r.window_name == legacy_window != windows_of[r.name]:
            tmux.tmux(cfg, "rename-window", "-t", r.window_id, windows_of[r.name])
        print(f"adopted {r.name}")
        acted = True

    windows = None
    skipped = set()
    for pane in to_start:
        acted = True
        if pane.name != queen and not Path(pane.dir).is_dir():
            # One stale entry must not keep the rest of the hive down.
            print(f"{'would skip' if dry_run else 'skipped'} {pane.name}: "
                  f"dir {pane.dir} does not exist", file=sys.stderr)
            skipped.add(pane.type)
            continue
        warn_untrusted(cfg, pane)
        if dry_run:
            print(f"would start {pane.name}")
            continue
        preflight(cfg, pane)
        if pane.name == queen:
            materialize_queen(cfg)
        if windows is None:
            windows = tmux.window_ids(cfg)
        window_id = windows.get(pane.window)
        tmux.start_pane(cfg, pane, window_id)
        if window_id is None:
            windows = tmux.window_ids(cfg)
        print(f"started {pane.name}  [{pane.dir}]  {expand_pane(cfg, pane)}")

    for r in to_stop:
        acted = True
        if not dry_run:
            tmux.tmux(cfg, "kill-pane", "-t", r.pane_id)
        print(f"{'would stop' if dry_run else 'stopped'} {r.name}")

    if skipped:
        warn(f"{len(skipped)} agent(s) {'would be ' if dry_run else ''}skipped: "
             "dir missing; see 'hive list'")
    if not acted and announce_idle:
        print("no changes")
    return 0


def cmd_up(cfg, args):
    if tmux.session_running(cfg):
        return reconcile(cfg)

    session = cfg["session"]
    desired = desired_panes(cfg)
    # The queen when enabled, else the first worker whose dir exists.
    first = next((p for p in desired if p.type == "queen" or Path(p.dir).is_dir()), None)
    if first is None:
        print("nothing to start: queen disabled and no agents" if not desired else
              "nothing to start: queen disabled and every agent dir is missing; see 'hive list'")
        return 0
    warn_untrusted(cfg, first)
    preflight(cfg, first)
    try:
        if first.type == "queen":
            materialize_queen(cfg)
        shell = [cfg["pane_shell"]] if cfg["pane_shell"] else []
        # Detached size is fixed so tiled panes are not tiny; attach resizes.
        out = tmux.tmux(cfg, "new-session", "-d", "-P", "-F", "#{pane_id}", "-s", session,
                        "-n", first.window, "-x", "200", "-y", "50", "-c", first.dir, *shell)
        # Also put [env] on the server so panes opened later inherit it.
        for key, value in cfg["env"].items():
            tmux.tmux(cfg, "set-environment", "-g", key, os.path.expandvars(value))
        tmux.setup_pane(cfg, first, out.stdout.strip())
        print(f"started session {session} (tmux -L {cfg['socket']})")
        print(f"started {first.name}  [{first.dir}]  {expand_pane(cfg, first)}")
        reconcile(cfg, announce_idle=False)
    except BaseException:
        # Do not leave a half-built session behind (the queen's tmux call may be what failed).
        tmux.tmux(cfg, "kill-session", "-t", "=" + session, check=False)
        print(f"hive: startup failed; removed session {session}", file=sys.stderr)
        raise
    return 0


def cmd_down(cfg, args):
    if not tmux.session_running(cfg):
        print(f"session {cfg['session']} not running")
        return 0
    tmux.tmux(cfg, "kill-session", "-t", "=" + cfg["session"])
    print(f"stopped session {cfg['session']}")
    # Stop the dedicated server too once nothing is left on it.
    if not tmux.tmux(cfg, "list-sessions", check=False).stdout.strip():
        tmux.tmux(cfg, "kill-server", check=False)
    return 0


def cmd_restart(cfg, args):
    if systemd_unit_active():
        # Restart through systemd so the tmux server stays in the service cgroup.
        return subprocess.run(["systemctl", "--user", "restart", unit_name()]).returncode
    hold_lock()
    cmd_down(cfg, args)
    return cmd_up(cfg, args)


def cmd_status(cfg, args):
    if not tmux.session_running(cfg):
        print("not running")
        return 1
    # pane_title last: it is the only field a program can put a tab in.
    fmt = "#{window_index}\t#{window_name}\t#{pane_index}\t#{pane_current_command}\t#{pane_title}"
    out = tmux.tmux(cfg, "list-panes", "-s", "-t", "=" + cfg["session"], "-F", fmt)
    print(f"session {cfg['session']}")
    current_window = None
    for line in out.stdout.splitlines():
        _, window, pane_index, running, title = line.split("\t", 4)
        if window != current_window:
            print(f"  {window}")
            current_window = window
        print(f"    pane {pane_index}: {title}  ({running})")
    print(f"attach: tmux -L {cfg['socket']} attach -t {cfg['session']}")
    return 0


def cmd_attach(cfg, args):
    if not tmux.session_running(cfg):
        die(f"session {cfg['session']} not running; run 'hive up'", 1)
    os.execvp("tmux", ["tmux", "-L", cfg["socket"], "attach", "-t", cfg["session"]])


def cmd_reconcile(cfg, args):
    return reconcile(cfg, dry_run=args.dry_run)


def add_parser(sub, name):
    if name == "up":
        sub.add_parser("up", help="start the session, or reconcile it with the config if running",
                       description="Start the session with the queen and every configured agent, "
                       "or reconcile it with the config if it is already running. Agents whose "
                       "dir is missing are skipped with a warning.")
    elif name == "down":
        sub.add_parser("down", help="stop the session (and the hive tmux server if empty)",
                       description="Stop the session, and the hive tmux server once it is empty. "
                       + BROKEN_CONFIG_NOTE)
    elif name == "restart":
        sub.add_parser("restart", help="restart via systemd if the unit is active, else down + up",
                       description="Restart via systemd if the hive.service unit is active, "
                       "else run down and then up.")
    elif name == "status":
        sub.add_parser("status", help="show windows and panes (exit 1 if not running)",
                       description="Show windows and panes; exit 1 if the session is not running. "
                       + BROKEN_CONFIG_NOTE)
    elif name == "attach":
        sub.add_parser("attach", help="attach to the session")
    elif name == "reconcile":
        p = sub.add_parser("reconcile", help="make the running session match the config",
                           description="Start missing panes, stop surplus ones and adopt panes "
                           "titled with a desired name, so the running session matches the config.")
        p.add_argument("--dry-run", action="store_true", help="only print what would change")
