"""config.toml: the profile's paths, reading, validation, edits, and `hive init`."""

import os
import re
import shlex
import socket
import tomllib
from importlib import resources
from pathlib import Path

from hive.configedit import ENV_KEY_RE, EditError, verify, write_atomic
from hive.drivers import DEFAULT_SYSTEM, DRIVERS
from hive.drivers.claude import CONFIG_DIR_ENV, CONFIG_DIR_ENV_MSG
from hive.inspect import DEFAULT_ROOTS
from hive.launch import check_launcher_command, default_shell, queen_command_line
from hive.paths import PathError, expanduser
from hive.reconcile import RESERVED_TYPES
from hive.util import ConfigError, die  # ConfigError lives in util so hive.launch can raise it

DEFAULT_SOCKET = "hive"
# A named profile (--profile NAME / HIVE_PROFILE): own config, lock, queen dir, socket, unit.
PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9-]*")

TOP_KEYS = {"prefix", "session", "tmux_socket", "login_shell", "shell",
            "defaults", "env", "service", "agents", "search_roots", "queen",
            "inspect_roots", "launchers", "nodes"}
DEFAULTS_KEYS = {"command", "launcher", "args", "system"}
LAUNCHER_KEYS = {"name", "command", "config_dir", "description", "system"}
LAUNCHER_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
AGENT_KEYS = {"type", "dir", "count", "indices", "command", "args", "env", "config_dir", "system"}
NODE_KEYS = {"name", "host", "hive", "profile", "description"}
QUEEN_KEYS = {"command", "args", "discover", "env", "config_dir", "enabled", "system"}
TYPE_RE = re.compile(r"[A-Za-z0-9._-]+")
# tmux rewrites or mis-targets names with these.
BAD_NAME_RE = re.compile(r"[.:\s]")


def config_home():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


_profile_option = None  # --profile, set by cli.run()


def profile_name():
    """The named profile (--profile, else HIVE_PROFILE), or None for the default profile."""
    name = _profile_option if _profile_option is not None else os.environ.get("HIVE_PROFILE") or None
    if name is None or name == "default":
        return None
    if not PROFILE_RE.fullmatch(name):
        raise ConfigError(f"profile name {name!r} must match {PROFILE_RE.pattern}")
    return name


def profile_dir():
    base = config_home() / "hive"
    name = profile_name()
    return base if name is None else base / "profiles" / name


def config_path():
    return profile_dir() / "config.toml"


def default_socket():
    """The default profile's tmux socket, read leniently; "hive" when unreadable or absent."""
    path = config_home() / "hive" / "config.toml"
    try:
        raw = read_config(path)
    except ConfigError:
        # Only the tmux_socket line: a broken prefix line must not hide the real socket.
        raw = top_level_names(path, ("tmux_socket",))
    sock = raw.get("tmux_socket", DEFAULT_SOCKET)
    return sock if isinstance(sock, str) and sock else DEFAULT_SOCKET


def socket_file(sock):
    """Where tmux -L puts the socket, normalized so aliases like ./hive compare equal."""
    base = f"{os.environ.get('TMUX_TMPDIR') or '/tmp'}/tmux-{os.getuid()}"
    return os.path.normpath(f"{base}/{sock}")  # tmux appends the name, even "/hive"


def refuse_socket_collision(sock, path):
    """A named profile must never reach the default profile's (production) tmux server."""
    if profile_name() is None:
        return
    if socket_file(sock) in (socket_file(DEFAULT_SOCKET), socket_file(default_socket())):
        raise ConfigError(f"{path}: tmux_socket {sock!r} is the default profile's socket; "
                          f"profile {profile_name()!r} needs its own (default hive-{profile_name()})")


# --- validation -----------------------------------------------------------

def check_keys(table, allowed, where, path):
    for key in table:
        if key not in allowed:
            raise ConfigError(f"{path}: unknown key '{key}' in {where} "
                              f"(allowed: {', '.join(sorted(allowed))})")


TOML_TYPES = {list: "an array", dict: "a table", int: "an integer", str: "a string"}


def check_type(value, expected, key, path):
    # bool is an int subclass; never accept it as a count
    if not isinstance(value, expected) or isinstance(value, bool):
        what = "an array of [[agents]] tables" if key == "agents" else TOML_TYPES[expected]
        raise ConfigError(f"{path}: '{key}' must be {what}")


def check_name(value, key, path):
    """prefix and session end up in tmux targets."""
    check_type(value, str, key, path)
    if not value or BAD_NAME_RE.search(value):
        raise ConfigError(f"{path}: '{key}' = {value!r} must be non-empty and contain no '.', "
                          "':' or whitespace (tmux rewrites or mis-targets them)")


def check_socket(value, key, path):
    """tmux -L takes any name without whitespace."""
    check_type(value, str, key, path)
    if not value or re.search(r"\s", value):
        raise ConfigError(f"{path}: '{key}' = {value!r} must be non-empty and contain no whitespace")


def check_text(value, key, path):
    """A non-blank string (command, shell)."""
    check_type(value, str, key, path)
    if not value.strip():
        raise ConfigError(f"{path}: '{key}' must not be empty")


def check_system(table, key, default, path):
    """Optional `system`: the agent system (driver) that runs the command."""
    value = table.get("system", default)
    check_type(value, str, key, path)
    if value not in DRIVERS:
        raise ConfigError(f"{path}: '{key}' = {value!r} is not a known system "
                          f"(known: {', '.join(DRIVERS)})")
    return value


def abs_path(text, label, path):
    """~ expanded, absolute; relative paths would depend on the caller's cwd."""
    if not text.strip():
        raise ConfigError(f"{path}: {label} must not be empty")
    try:
        directory = expanduser(text)
    except PathError as e:
        raise ConfigError(f"{path}: {label}: {e}") from None
    if not directory.is_absolute():
        raise ConfigError(f"{path}: {label} '{text}' must be an absolute path or start with ~")
    return str(directory)


def check_env(env, where, path):
    check_type(env, dict, where, path)
    for key, value in env.items():
        if not ENV_KEY_RE.fullmatch(key):
            raise ConfigError(f"{path}: {where}.{key}: env names must match {ENV_KEY_RE.pattern}")
        if not isinstance(value, str):
            raise ConfigError(f"{path}: {where}.{key} must be a string")
        if key == CONFIG_DIR_ENV:
            raise ConfigError(f"{path}: {where}.{CONFIG_DIR_ENV}: {CONFIG_DIR_ENV_MSG}")


def check_args(value, key, path):
    """Optional launcher flags: a list of non-empty strings."""
    if not isinstance(value, list) or not all(isinstance(a, str) and a for a in value):
        raise ConfigError(f"{path}: '{key}' must be an array of non-empty strings")
    return value


def check_config_dir(table, where, path):
    """Optional config_dir: ~ expanded, absolute. Only locates the trust file."""
    value = table.get("config_dir")
    if value is None:
        return None
    check_type(value, str, f"{where}.config_dir", path)
    return abs_path(value, f"{where}.config_dir", path)


def read_config(path):
    """Parse config.toml; ConfigError on a missing, unreadable or malformed file."""
    if not path.exists():
        raise ConfigError(f"{path} not found; run 'hive init' to create it")
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"cannot read {path}: {getattr(e, 'strerror', None) or e}") from None


def load_config():
    """The validated config, or exit 2 with a message."""
    try:
        return parse_config()
    except (ConfigError, PathError) as e:
        die(str(e))


def lenient_config():
    """(config for `down` and `status`, warning or None) that works with a broken config.

    Falls back to the defaults for names the config does not set. A name that is set but
    invalid is an error: guessing the default socket could stop a different hive.
    """
    path = config_path()
    if not path.exists():
        raise ConfigError(f"{path} not found; run 'hive init' to create it")
    try:
        return parse_config(), None
    except (ConfigError, PathError) as e:
        problem = str(e)
    try:
        raw = read_config(path)
    except ConfigError:
        raw = top_level_names(path)

    def pick(key, default, check=check_name):
        if key not in raw:
            return default
        check(raw[key], key, path)
        return raw[key]

    profile = profile_name()
    prefix = pick("prefix", profile or socket.gethostname().split(".")[0])
    session = pick("session", f"{prefix}-agents")
    sock = pick("tmux_socket", f"hive-{profile}" if profile else DEFAULT_SOCKET, check_socket)
    refuse_socket_collision(sock, path)
    return ({"prefix": prefix, "session": session, "socket": sock, "profile": profile,
             "pane_shell": None, "env": {}, "agents": [], "config_path": str(path)},
            f"{problem}\n  using session {session} on socket {sock} (from the parsable lines "
            "of the config, else the defaults)")


def top_level_names(path, keys=("prefix", "session", "tmux_socket")):
    """prefix, session and tmux_socket from single top-level lines of a config TOML cannot parse.

    A typo elsewhere in the file must not send `down` to the default socket when the
    config names its own: that would stop a different hive."""
    found = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return found
    for line in lines:
        if line.lstrip().startswith("["):
            break  # top-level keys end at the first table
        m = re.match(rf"""\s*["']?({'|'.join(keys)})["']?\s*=""", line)
        if m:
            try:
                found.update(tomllib.loads(line))
            except tomllib.TOMLDecodeError as e:
                # Set but unreadable: guessing the default could hit another hive.
                raise ConfigError(f"{path}: cannot parse the {m.group(1)} line ({e}): {line.strip()}")
    return found


def parse_defaults(raw, path):
    """[defaults]: (command or None, args, launcher or None, system)."""
    defaults = raw.get("defaults", {})
    check_type(defaults, dict, "defaults", path)
    check_keys(defaults, DEFAULTS_KEYS, "[defaults]", path)
    command = defaults.get("command")
    if command is not None:
        check_text(command, "defaults.command", path)
    args = check_args(defaults.get("args", []), "defaults.args", path)
    # Not checked against [[launchers]]: it may name a discover record, resolved at use time.
    launcher = defaults.get("launcher")
    if launcher is not None:
        check_type(launcher, str, "defaults.launcher", path)
    system = check_system(defaults, "defaults.system", DEFAULT_SYSTEM, path)
    return command, args, launcher, system


def parse_launchers(raw, default_system, path):
    raw_launchers = raw.get("launchers", [])
    check_type(raw_launchers, list, "launchers", path)
    launchers = []
    launcher_names = set()
    for i, entry in enumerate(raw_launchers, 1):
        where = f"launchers[{i}]"
        check_type(entry, dict, where, path)
        check_keys(entry, LAUNCHER_KEYS, where, path)
        for key in ("name", "command"):
            if key not in entry:
                raise ConfigError(f"{path}: {where} is missing required key '{key}'")
            check_text(entry[key], f"{where}.{key}", path)
        if not LAUNCHER_NAME_RE.fullmatch(entry["name"]):
            raise ConfigError(f"{path}: {where}.name '{entry['name']}' must match [a-z0-9][a-z0-9-]*")
        if entry["name"] in launcher_names:
            raise ConfigError(f"{path}: duplicate launcher name '{entry['name']}'")
        launcher_names.add(entry["name"])
        system = check_system(entry, f"{where}.system", default_system, path)
        check_launcher_command(entry["command"], f"{path}: {where}.command", system)
        description = entry.get("description")
        if description is not None:
            check_type(description, str, f"{where}.description", path)
        launchers.append({"name": entry["name"], "command": entry["command"],
                          "config_dir": check_config_dir(entry, where, path),
                          "description": description, "system": system})
    return launchers


def parse_nodes(raw, path):
    """[[nodes]]: remote hives that `hive --node NAME` reaches over ssh (plan D8)."""
    raw_nodes = raw.get("nodes", [])
    check_type(raw_nodes, list, "nodes", path)
    nodes = []
    for i, entry in enumerate(raw_nodes, 1):
        where = f"nodes[{i}]"
        check_type(entry, dict, where, path)
        check_keys(entry, NODE_KEYS, where, path)
        for key in ("name", "host"):
            if key not in entry:
                raise ConfigError(f"{path}: {where} is missing required key '{key}'")
        check_type(entry["name"], str, f"{where}.name", path)
        if not LAUNCHER_NAME_RE.fullmatch(entry["name"]):
            raise ConfigError(f"{path}: {where}.name '{entry['name']}' must match "
                              f"{LAUNCHER_NAME_RE.pattern}")
        if any(n["name"] == entry["name"] for n in nodes):
            raise ConfigError(f"{path}: duplicate node name '{entry['name']}'")
        host = entry["host"]
        check_type(host, str, f"{where}.host", path)
        # ssh reads a leading '-' as an option.
        if not host or host.startswith("-") or re.search(r"\s", host):
            raise ConfigError(f"{path}: {where}.host {host!r} must be non-empty, contain no "
                              "whitespace and not start with '-'")
        exe = entry.get("hive", "hive")
        check_text(exe, f"{where}.hive", path)
        profile = entry.get("profile")
        if profile is not None:
            check_type(profile, str, f"{where}.profile", path)
            if profile != "default" and not PROFILE_RE.fullmatch(profile):
                raise ConfigError(f"{path}: {where}.profile {profile!r} must match "
                                  f"{PROFILE_RE.pattern} or be 'default'")
        description = entry.get("description")
        if description is not None:
            check_type(description, str, f"{where}.description", path)
        nodes.append({"name": entry["name"], "host": host, "hive": exe, "profile": profile,
                      "description": description})
    return nodes


def parse_env(raw, path):
    env = raw.get("env", {})
    check_env(env, "env", path)
    return env


def parse_queen(raw, default_command, default_args, default_system, path):
    """[queen]: (the queen's pane entry without its dir, discover command or None)."""
    queen = raw.get("queen", {})
    check_type(queen, dict, "queen", path)
    check_keys(queen, QUEEN_KEYS, "[queen]", path)
    system = check_system(queen, "queen.system", default_system, path)
    command = queen.get("command", default_command or DRIVERS[system].default_command)
    check_text(command, "queen.command", path)
    args = check_args(queen.get("args", default_args), "queen.args", path)
    discover = queen.get("discover")
    if discover is not None:
        check_text(discover, "queen.discover", path)
    env = queen.get("env", {})
    check_env(env, "queen.env", path)
    config_dir = check_config_dir(queen, "queen", path)
    enabled = queen.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError(f"{path}: 'queen.enabled' must be true or false")
    return ({"type": "queen", "command": queen_command_line(command, args, system),
             "args": args, "env": env, "config_dir": config_dir, "enabled": enabled,
             "system": system}, discover)


def parse_agents(raw, default_command, default_args, default_system, path):
    raw_agents = raw.get("agents", [])
    check_type(raw_agents, list, "agents", path)

    agents = []
    seen = set()
    for i, entry in enumerate(raw_agents, 1):
        where = f"agents[{i}]"
        check_type(entry, dict, where, path)
        check_keys(entry, AGENT_KEYS, where, path)
        for key in ("type", "dir"):
            if key not in entry:
                raise ConfigError(f"{path}: {where} is missing required key '{key}'")
        check_type(entry["type"], str, f"{where}.type", path)
        check_type(entry["dir"], str, f"{where}.dir", path)
        kind = entry["type"]
        if not kind:
            raise ConfigError(f"{path}: {where}.type must not be empty")
        if kind in RESERVED_TYPES:
            raise ConfigError(f"{path}: {where}.type '{kind}' is reserved for the hive queen")
        if not TYPE_RE.fullmatch(kind):
            raise ConfigError(f"{path}: {where}.type '{kind}' may only contain letters, digits, "
                              "'.', '_' and '-'")
        if kind in seen:
            raise ConfigError(f"{path}: duplicate agent type '{kind}'")
        seen.add(kind)

        directory = abs_path(entry["dir"], f"{where}.dir", path)

        if "indices" in entry:
            if "count" in entry:
                raise ConfigError(f"{path}: {where} has both 'count' and 'indices'; keep one")
            indices = entry["indices"]
            check_type(indices, list, f"{where}.indices", path)
            if (any(not isinstance(i, int) or isinstance(i, bool) or i < 1 for i in indices)
                    or len(set(indices)) != len(indices)):
                raise ConfigError(f"{path}: {where}.indices must be distinct integers >= 1")
            indices = sorted(indices)
        else:
            count = entry.get("count", 1)
            check_type(count, int, f"{where}.count", path)
            if count < 0:
                raise ConfigError(f"{path}: {where}.count must be >= 0")
            indices = list(range(1, count + 1))

        command = entry.get("command", default_command)
        if command is None:
            raise ConfigError(f"{path}: {where} has no 'command' and [defaults] has no "
                              "'command'")
        check_text(command, f"{where}.command", path)

        agent_args = check_args(entry.get("args", default_args), f"{where}.args", path)

        agent_env = entry.get("env", {})
        check_env(agent_env, f"{where}.env", path)

        # `count` is the number of instances; `indices` their numbers N (D6).
        agents.append({"type": kind, "dir": directory, "count": len(indices),
                       "indices": indices, "command": command,
                       "args": agent_args, "env": agent_env,
                       "config_dir": check_config_dir(entry, where, path),
                       "system": check_system(entry, f"{where}.system", default_system, path)})
    return agents


def parse_config():
    path = config_path()
    raw = read_config(path)

    check_keys(raw, TOP_KEYS, "top level", path)

    profile = profile_name()
    prefix = raw.get("prefix", profile or socket.gethostname().split(".")[0])
    check_name(prefix, "prefix", path)
    # The machine part of every instance name; keep it to the type characters.
    if not TYPE_RE.fullmatch(prefix):
        raise ConfigError(f"{path}: prefix {prefix!r} may only contain letters, digits, '_' and '-'")
    session = raw.get("session", f"{prefix}-agents")
    check_name(session, "session", path)
    tmux_socket = raw.get("tmux_socket", f"hive-{profile}" if profile else DEFAULT_SOCKET)
    check_socket(tmux_socket, "tmux_socket", path)
    refuse_socket_collision(tmux_socket, path)

    login_shell = raw.get("login_shell", True)
    if not isinstance(login_shell, bool):
        raise ConfigError(f"{path}: 'login_shell' must be true or false")
    shell = raw.get("shell", default_shell())
    check_text(shell, "shell", path)

    default_command, default_args, default_launcher, system = parse_defaults(raw, path)
    launchers = parse_launchers(raw, system, path)
    env = parse_env(raw, path)

    service = raw.get("service", {})
    check_type(service, dict, "service", path)
    check_keys(service, {"after"}, "[service]", path)
    after = service.get("after", [])
    if not isinstance(after, list) or not all(isinstance(a, str) for a in after):
        raise ConfigError(f"{path}: service.after must be an array of strings")

    search_roots = raw.get("search_roots", [])
    if not isinstance(search_roots, list) or not all(isinstance(r, str) for r in search_roots):
        raise ConfigError(f"{path}: search_roots must be an array of strings")
    search_roots = [abs_path(r, "search_roots entry", path) for r in search_roots]

    inspect_roots = raw.get("inspect_roots", DEFAULT_ROOTS)
    if not isinstance(inspect_roots, list) or not all(isinstance(r, str) for r in inspect_roots):
        raise ConfigError(f"{path}: inspect_roots must be an array of strings")
    inspect_roots = [abs_path(r, "inspect_roots entry", path) for r in inspect_roots]

    queen, discover = parse_queen(raw, default_command, default_args, system, path)
    agents = parse_agents(raw, default_command, default_args, system, path)
    nodes = parse_nodes(raw, path)

    return {
        "prefix": prefix,
        "session": session,
        "socket": tmux_socket,
        "profile": profile,
        # Pane command: a login shell, or None for tmux's default-command.
        "pane_shell": shlex.join([shell, "-l"]) if login_shell else None,
        "env": env,
        "after": after,
        "agents": agents,
        "search_roots": search_roots,
        "inspect_roots": inspect_roots,
        "queen": {**queen, "dir": str(profile_dir() / "queen")},
        "discover": discover,
        "launchers": launchers,
        "default_launcher": default_launcher,
        "system": system,
        "nodes": nodes,
        "config_path": str(path),
    }


# --- edits ----------------------------------------------------------------

def edit_config(cfg, edit, mutate):
    """Apply a text edit to config.toml: verified against `mutate`, then written atomically."""
    path = cfg["config_path"]
    try:
        with open(path, encoding="utf-8", newline="") as f:
            old = f.read()
    except (OSError, UnicodeDecodeError) as e:
        die(f"cannot read {path}: {getattr(e, 'strerror', None) or e}", 1)
    try:
        new = edit(old)
        verify(old, new, mutate, path)
    except EditError as e:
        die(str(e), 2)
    try:
        write_atomic(path, new)
    except OSError as e:
        die(f"cannot write {path}: {e.strerror or e}", 1)


def check_config_writable(cfg):
    """Fail before side effects (seeding trust) when the edit cannot be written."""
    path = Path(cfg["config_path"])
    if not (os.access(path, os.W_OK) and os.access(path.parent, os.W_OK)):
        die(f"cannot write {path}: not writable (the file and its directory must be)", 1)


def expand_config_dir(text, where):
    directory = expanduser(text)
    if not directory.is_absolute():
        die(f"{where} '{text}' must be absolute or start with ~")
    return str(directory)


# --- init -----------------------------------------------------------------

def cmd_init(args):
    path = config_path()
    if path.exists():
        print(f"{path} already exists")
    else:
        example = resources.files("hive").joinpath("config.example.toml").read_text()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(example)
        except OSError as e:
            die(f"cannot write {path}: {e.strerror or e}", 1)
        print(f"wrote {path}; it has no agents yet, so 'hive up' starts only the queen; "
              "add agents with 'hive spawn DIR' or by editing it")
    cfg, _ = lenient_config()
    print(f"config={path} session={cfg['session']} socket={cfg['socket']}; "
          "set tmux_socket in the config to keep a test or isolated config off your "
          "real hive's tmux server")
    return 0


def add_parser(sub, name):
    assert name == "init"
    sub.add_parser("init", help="write an example config if none exists")
