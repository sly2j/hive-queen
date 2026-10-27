"""The hive's tmux server: every tmux call, and starting and listing panes."""

import os
import shlex
import subprocess

from hive.drivers import DRIVERS
from hive.launch import expand_pane
from hive.reconcile import RunningPane, desired_panes, parse_legacy_name, parse_name, queen_name
from hive.util import die

# Never handed to the tmux server, so no pane inherits them (see each driver's env_scrub).
SESSION_ENV = frozenset().union(*(d.env_scrub for d in DRIVERS.values()))


def tmux_env():
    # HIVE_PROFILE too: a named profile's panes export their own, others must not inherit one.
    return {k: v for k, v in os.environ.items()
            if k not in SESSION_ENV and k != "HIVE_PROFILE"}


def tmux(cfg, *args, check=True):
    cmd = ["tmux", "-L", cfg["socket"], *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=tmux_env())
    except FileNotFoundError:
        die("tmux not found in PATH", 1)
    if check and result.returncode != 0:
        die(f"{' '.join(cmd)} failed: {result.stderr.strip()}", 1)
    return result


def session_running(cfg):
    return tmux(cfg, "has-session", "-t", "=" + cfg["session"], check=False).returncode == 0


def shell_line(cfg, directory, command, env=None):
    """One shell line: [env] exports, then the type's env exports, cd, command."""
    parts = []
    for key, value in [*cfg["env"].items(), *(env or {}).items()]:
        # Escape what is special inside double quotes; leave $ so variables expand.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`")
        parts.append(f'export {key}="{escaped}"')
    if cfg.get("profile"):
        # Plain `hive` in the pane (a queen or worker) then addresses this profile.
        parts.append(f"export HIVE_PROFILE={cfg['profile']}")
    parts.append(f"cd {shlex.quote(directory)}")
    parts.append(command)
    return " && ".join(parts)


def running_panes(cfg):
    """Return ({name: RunningPane}, unmanaged) for the session's panes.

    A pane is managed when it has @hive_name, or (adopted) when its title equals
    a desired name exactly; everything else is unmanaged and never touched.
    A pane tagged with a legacy name whose canonical name is desired is adopted
    under the canonical name (reconcile retags and renames it).
    """
    fmt = "#{pane_id}\t#{window_id}\t#{window_name}\t#{@hive_name}\t#{pane_title}"
    out = tmux(cfg, "list-panes", "-s", "-t", "=" + cfg["session"], "-F", fmt)
    desired = {p.name for p in desired_panes(cfg)}
    running, unmanaged = {}, []
    for line in out.stdout.splitlines():
        pane_id, window_id, window_name, hive_name, title = line.split("\t", 4)
        adopted = False
        name = hive_name
        if not name and title in desired:
            name, adopted = title, True
        if name and name not in desired:
            legacy = parse_legacy_name(cfg["prefix"], name)
            if legacy:
                canonical = (queen_name(cfg["prefix"]) if legacy[0] == "queen"
                             else f"{legacy[0]}-{cfg['prefix']}-{legacy[1]}")
                if canonical in desired:
                    name, adopted = canonical, True
        parsed = parse_name(cfg["prefix"], name) if name else None
        if parsed is None:
            unmanaged.append({"pane": pane_id, "window": window_name, "title": title})
            continue
        running[name] = RunningPane(pane_id, window_id, window_name, name,
                                    parsed[0], parsed[1], adopted)
    return running, unmanaged


def window_ids(cfg):
    out = tmux(cfg, "list-windows", "-t", "=" + cfg["session"], "-F", "#{window_id}\t#{window_name}")
    return {name: wid for wid, name in (line.split("\t", 1) for line in out.stdout.splitlines())}


def setup_pane(cfg, pane, pane_id):
    """Title, tag, and type the command into a freshly created pane."""
    tmux(cfg, "select-pane", "-t", pane_id, "-T", pane.name)
    # Keep apps from overwriting the title; ignore tmux versions without the option.
    tmux(cfg, "set-option", "-p", "-t", pane_id, "allow-set-title", "off", check=False)
    tmux(cfg, "set-option", "-p", "-t", pane_id, "@hive_name", pane.name)
    tmux(cfg, "send-keys", "-t", pane_id, "-l",
         shell_line(cfg, pane.dir, expand_pane(cfg, pane), pane.env))
    tmux(cfg, "send-keys", "-t", pane_id, "Enter")


def start_pane(cfg, pane, window_id):
    """Start a pane in a new window (window_id None) or beside the window's last pane."""
    fmt = ["-P", "-F", "#{pane_id}"]
    shell = [cfg["pane_shell"]] if cfg["pane_shell"] else []
    if window_id is None:
        out = tmux(cfg, "new-window", "-d", *fmt, "-t", f"={cfg['session']}:", "-n", pane.window,
                   "-c", pane.dir, *shell)
        pane_id = out.stdout.strip()
    else:
        last = tmux(cfg, "list-panes", "-t", window_id, "-F", "#{pane_id}").stdout.split()[-1]
        out = tmux(cfg, "split-window", "-d", *fmt, "-t", last, "-c", pane.dir, *shell)
        pane_id = out.stdout.strip()
        # Re-tile after every split so the next split has room.
        tmux(cfg, "select-layout", "-t", pane_id, "tiled")
    setup_pane(cfg, pane, pane_id)
    return pane_id
