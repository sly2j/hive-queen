"""What a pane runs: command templates, placeholder expansion, and pre-start checks."""

import os
import pwd
import re
import shlex
import shutil

from hive.drivers import DEFAULT_SYSTEM, get_driver
from hive.drivers.common import version_tuple
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


def expand_pane(cfg, pane, session_id=None):
    """The pane's command line. With a session id, {session_id} is expanded; when neither the
    command nor an arg has it, the driver's session args are appended. Without one, nothing is
    appended and {session_id} stays literal (lifecycle prints, preflight).

    A `sh -c '...'` wrapper must carry {session_id} inside its quotes: an appended flag would
    become the wrapper's $0.
    """
    values = dict(name=pane.name, type=pane.type, index=pane.index, dir=pane.dir,
                  prefix=cfg["prefix"])
    if session_id is None:
        return expand_command(pane.command, pane.args, **values)
    command = expand_command(pane.command, pane.args, session_id=session_id, **values)
    if "{session_id}" in pane.command or any("{session_id}" in a for a in pane.args):
        return command
    extra = " ".join(shlex.quote(a) for a in get_driver(pane.system).session_args(session_id))
    return f"{command} {extra}" if extra else command


def check_launcher_command(command, where, system=DEFAULT_SYSTEM):
    driver = get_driver(system)
    tokens = [*driver.required_placeholders, *driver.required_tokens]
    if not all(t in command for t in tokens):
        raise ConfigError(f"{where} must contain {' and '.join(tokens)}")


def warn_untrusted(cfg, pane):
    """Warn only: hive never records trust without an explicit --trust."""
    driver = get_driver(pane.system)
    root, _, trusted = driver.trust_state(pane.dir, pane.config_dir)
    if not trusted:
        warn(f"untrusted {pane.name} {root}; attach and accept the {driver.name} trust prompt, "
             "or run 'hive spawn --trust' after the user confirms")


_warned = set()


def check_version(system, where):
    """Raise ConfigError when the installed binary is older than the driver's minimum; warn when
    its version cannot be read. A driver without min_version is not probed."""
    driver = get_driver(system)
    if driver.min_version is None:
        return
    minimum = ".".join(str(n) for n in driver.min_version)
    version = driver.probe(driver.binary)
    if version is None:
        warn(f"{where}: cannot read the {driver.binary} version ({driver.binary} --version); "
             f"need {minimum} or newer: {driver.install_hint}")
        return
    if version_tuple(version) < driver.min_version:
        raise ConfigError(f"{where}: {driver.binary} {version} is older than {minimum}, the "
                          f"oldest {driver.name} version hive supports; install a newer one: "
                          f"{driver.install_hint}")


def preflight(cfg, pane):
    """Warn (never fail) about a command that probably will not work as a pane."""
    command = expand_pane(cfg, pane)
    driver = get_driver(pane.system)
    if ("version", pane.system) not in _warned:
        _warned.add(("version", pane.system))
        try:
            check_version(pane.system, pane.name)
        except ConfigError as e:
            warn(str(e))
    for token in driver.required_tokens:
        if token not in command and (token, command) not in _warned:
            _warned.add((token, command))
            warn(f"{pane.name}: command has no {token}, so the pane will not be "
                 f"reachable from {driver.name}'s remote sessions: {command}")
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
