"""What a pane runs: command templates, placeholder expansion, and pre-start checks."""

import os
import pwd
import re
import shlex
import shutil

from hive.drivers import DEFAULT_SYSTEM, get_driver
from hive.util import ConfigError, warn


def queen_command_line(command, args=(), system=DEFAULT_SYSTEM):
    """The queen's command plus its system's restricting flags (see the driver's queen_extras)."""
    return get_driver(system).queen_extras(command, args)


def default_shell():
    # passwd first: the systemd user manager's $SHELL can be stale.
    try:
        return pwd.getpwuid(os.getuid()).pw_shell or os.environ.get("SHELL") or "/bin/sh"
    except KeyError:
        return os.environ.get("SHELL") or "/bin/sh"


def expand(command, **values):
    # Plain replace, not str.format, so ${VAR} and other braces survive.
    for key, value in values.items():
        command = command.replace("{" + key + "}", str(value))
    return command


def expand_command(command, args, **values):
    """Expand the command, then place the quoted, expanded args: at every {args}, else appended."""
    quoted = " ".join(shlex.quote(expand(a, **values)) for a in args)
    command = expand(command, **values)
    if "{args}" in command:
        return command.replace("{args}", quoted)
    return f"{command} {quoted}" if quoted else command


def expand_pane(cfg, pane):
    return expand_command(pane.command, pane.args, name=pane.name, type=pane.type,
                          index=pane.index, dir=pane.dir, prefix=cfg["prefix"])


def check_launcher_command(command, where, system=DEFAULT_SYSTEM):
    tokens = ["{name}", *get_driver(system).required_tokens]
    if not all(t in command for t in tokens):
        raise ConfigError(f"{where} must contain {' and '.join(tokens)}")


def warn_untrusted(cfg, pane):
    """Warn only: hive never records trust without an explicit --trust."""
    root, _, trusted = get_driver(pane.system).trust_state(pane.dir, pane.config_dir)
    if not trusted:
        warn(f"untrusted {pane.name} {root}; attach and accept Claude's trust prompt, "
             "or run 'hive spawn --trust' after the user confirms")


_warned = set()


def preflight(cfg, pane):
    """Warn (never fail) about a command that probably will not work as a pane."""
    command = expand_pane(cfg, pane)
    for token in get_driver(pane.system).required_tokens:
        if token not in command and (token, command) not in _warned:
            _warned.add((token, command))
            warn(f"{pane.name}: command has no {token}, so the pane will not be "
                 f"reachable from Claude's remote sessions: {command}")
    try:
        tokens = shlex.split(command)
    except ValueError:
        return
    # Skip leading VAR=value assignments.
    program = next((t for t in tokens if not re.fullmatch(r"[A-Za-z_]\w*=.*", t)), None)
    if program and ("which", program) not in _warned and not shutil.which(program):
        _warned.add(("which", program))
        warn(f"{pane.name}: '{program}' not found in PATH; the pane will show 'command not "
             "found' (the pane's login shell may have a different PATH)")
