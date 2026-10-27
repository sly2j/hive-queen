"""What a pane runs: command templates, placeholder expansion, and pre-start checks."""

import os
import pwd
import re
import shlex
import shutil

from hive.activity import hook_cmd, status_file
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


def expand_pane(cfg, pane, session_id=None, resume=False):
    """The pane's command line. With a session id, {session_id} is expanded; when neither the
    command nor an arg has it, the driver's session args are appended; the driver's status-hook
    flags are always appended. Without one, nothing is appended and {session_id} stays literal
    (lifecycle prints, preflight).

    With resume, the driver's resume args for that id go first in the args (so at {args}, else
    appended), and its session args are neither appended nor kept: `--session-id {session_id}`
    (or `=`) is dropped from the command and args (Claude refuses both flags at once).

    A `sh -c '...'` wrapper must pass appended flags through: `sh -c '... exec claude "$@"' sh`;
    otherwise they become its $0, and {session_id} must sit inside its quotes.
    """
    values = dict(name=pane.name, type=pane.type, index=pane.index, dir=pane.dir,
                  prefix=cfg["prefix"])
    if session_id is None:
        return expand_command(pane.command, pane.args, **values)
    driver = get_driver(pane.system)
    command, args = pane.command, list(pane.args)
    if resume:
        command, args = drop_session_args(driver, command, args)
        args = [*driver.resume_args(session_id), *args]
    expanded = expand_command(command, args, session_id=session_id, **values)
    extra = []
    if not resume and not ("{session_id}" in command or any("{session_id}" in a for a in args)):
        extra += driver.session_args(session_id)
    extra += driver.hook_args(hook_cmd(), status_file(cfg, pane.name))
    quoted = " ".join(shlex.quote(a) for a in extra)
    return f"{expanded} {quoted}" if quoted else expanded


def drop_session_args(driver, command, args):
    """Command and args without the driver's session args written with {session_id}, as
    `--flag {session_id}` or `--flag={session_id}`."""
    words = driver.session_args("{session_id}")
    if not words:
        return command, args
    forms = [" ".join(words)] + (["=".join(words)] if len(words) == 2 else [])
    # Each word optionally quoted, separated by whitespace or `=`.
    pattern = r"(?:\s+|=)".join(rf"(['\"]?){re.escape(w)}\{k + 1}" for k, w in enumerate(words))
    command = re.sub(r"\s*" + pattern + r"(?=\s|'|\"|$)", "", command)
    n, kept, i = len(words), [], 0
    while i < len(args):
        if args[i:i + n] == words:
            i += n
            continue
        if args[i] not in forms:
            kept.append(args[i])
        i += 1
    return command, kept


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
