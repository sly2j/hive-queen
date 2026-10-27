"""The systemd user unit: install-service, uninstall-service, and the unit's state."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from hive.config import load_config, profile_name
from hive.util import die

UNIT_TEMPLATE = """\
[Unit]
Description=hive: agent sessions in tmux
Wants=network-online.target
After={after}

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
{extra_env}ExecStart={exe}{profile} up
ExecStop={exe}{profile} down
# The tmux server forked by `hive up` stays in this cgroup while the unit is
# active. tmux may move pane processes into their own tmux-spawn-*.scope units;
# `hive down` ends them by killing the session.
KillMode=control-group

[Install]
WantedBy=default.target
"""


def unit_name():
    name = profile_name()
    return "hive.service" if name is None else f"hive-{name}.service"


def systemd_unit_active():
    if not shutil.which("systemctl"):
        return False
    result = subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit_name()])
    return result.returncode == 0


def unit_path():
    # Where the systemd user manager looks, whatever XDG_CONFIG_HOME says here.
    return Path.home() / ".config" / "systemd" / "user" / unit_name()


def systemctl(*args, check=True):
    if not shutil.which("systemctl"):
        die("systemctl not found", 1)
    result = subprocess.run(["systemctl", "--user", *args])
    if check and result.returncode != 0:
        die(f"systemctl --user {' '.join(args)} failed", 1)
    return result


def unit_quote(text, command=True):
    """Escape for an ExecStart (command) or Environment value: %, $, and quote when needed."""
    text = text.replace("%", "%%")
    if command:
        text = text.replace("$", "$$")
    if re.search(r'[\s"\'\\]', text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def service_exe():
    """The hive executable for the unit: %h/.local/bin/hive unless installed elsewhere."""
    found = shutil.which("hive")
    default = Path.home() / ".local" / "bin" / "hive"
    if found is None or Path(found).absolute() == default:
        return "%h/.local/bin/hive"
    return unit_quote(str(Path(found).absolute()))


def service_extra_env():
    """Pass a non-default XDG_CONFIG_HOME through, so the service reads the same config."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if not xdg or Path(xdg) == Path.home() / ".config":
        return ""
    return "Environment=" + unit_quote(f"XDG_CONFIG_HOME={xdg}", command=False) + "\n"


def die_if_macos(command):
    if sys.platform == "darwin":
        die(f"{command} is Linux-only (systemd); on macOS run 'hive up' from a launchd "
            "LaunchAgent, see the README section 'Run at login on macOS'", 1)


def cmd_install_service(args):
    die_if_macos("install-service")
    if not shutil.which("systemctl"):
        die("systemctl not found", 1)
    cfg = load_config()
    after = " ".join(["network-online.target", *cfg["after"]])
    path = unit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        profile = f" --profile {profile_name()}" if profile_name() else ""
        path.write_text(UNIT_TEMPLATE.format(after=after, exe=service_exe(), profile=profile,
                                             extra_env=service_extra_env()))
    except OSError as e:
        die(f"cannot write {path}: {e.strerror or e}", 1)
    print(f"wrote {path}")
    systemctl("daemon-reload")
    if args.enable:
        systemctl("enable", "--now", unit_name())
    else:
        print(f"next: systemctl --user enable --now {unit_name()}\n"
              "to start at boot without logging in: loginctl enable-linger $USER")
    return 0


def cmd_uninstall_service(args):
    die_if_macos("uninstall-service")
    path = unit_path()
    if not path.exists():
        print(f"not installed: {path} does not exist")
        return 0
    systemctl("disable", "--now", unit_name(), check=False)
    try:
        path.unlink()
    except OSError as e:
        die(f"cannot remove {path}: {e.strerror or e}", 1)
    print(f"removed {path}")
    systemctl("daemon-reload")
    return 0


def add_parser(sub, name):
    if name == "install-service":
        p = sub.add_parser("install-service", help="write the systemd user unit")
        p.add_argument("--enable", action="store_true", help="also enable and start it now")
    elif name == "uninstall-service":
        sub.add_parser("uninstall-service", help="disable and remove the systemd user unit")
