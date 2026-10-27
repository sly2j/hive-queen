"""Remote nodes: `hive --node NAME <command>` runs the command on another machine's hive over ssh.

A node is a `[[nodes]]` entry in config.toml (plan D8). The local side only builds the ssh
command line and passes stdio and the exit code through; the remote hive does the work under its
own config, lock and tmux server. A queen-less node sets `[queen] enabled = false` in its own
config.
"""

import shlex
import subprocess

from hive import config
from hive.util import ConfigError, die, quote

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
UNREACHABLE = 255  # ssh's own exit code for connection and authentication failures
# Options the remote argv may start with; anything else (--profile above all) is refused.
REMOTE_OPTIONS = ("--version", "-h", "--help")


def split_node_argv(argv):
    """(node, local --profile value or None, remote argv) for `[--profile P] --node NAME ...`
    (either option also as --opt=VALUE); else None, and the normal parser takes over.
    Everything after --node NAME goes to the remote hive."""
    profile = None
    i = 0
    while i < len(argv):
        name, eq, value = argv[i].partition("=")
        if name not in ("--node", "--profile"):
            return None
        if not eq:
            if i + 1 >= len(argv):
                return None  # argparse reports the missing value
            i += 1
            value = argv[i]
        i += 1
        if name == "--node":
            return value, profile, argv[i:]
        profile = value
    return None


def load_nodes():
    """The [[nodes]] table only: a node stays reachable while the rest of the config is broken."""
    path = config.config_path()
    return config.parse_nodes(config.read_config(path), path)


def find_node(nodes, name):
    for node in nodes:
        if node["name"] == name:
            return node
    known = ", ".join(n["name"] for n in nodes) or "none; add a [[nodes]] entry to config.toml"
    raise ConfigError(f"unknown node {name!r} (known: {known})")


def node_argv(node, profile, argv):
    """The ssh command line that runs `hive argv` on `node`; `profile` is the local profile.

    A named local profile (a test hive) may only reach a named, non-default remote profile, so
    it can never drive a production hive. The default remote profile gets no --profile option,
    so hives older than profiles work as nodes.
    """
    remote = node["profile"]
    if profile is not None and remote in (None, "default"):
        raise ConfigError(f"node {node['name']!r}: profile {profile!r} may only reach a named "
                          f"remote profile; set profile = \"<name>\" (not \"default\") in its "
                          "[[nodes]] entry")
    words = [node["hive"]]
    if remote not in (None, "default"):
        words += ["--profile", remote]
    return [*SSH, node["host"], "--", shlex.join([*words, *argv])]


def run_remote(name, argv):
    """Run `hive argv` on node `name`; returns the remote exit code (ssh failure: exit 1)."""
    if not argv:
        die(f"hive --node {name} needs a subcommand")
    if argv[0] == "attach":
        die("hive --node: attach needs a terminal; run `ssh -t HOST hive attach` yourself")
    if argv[0].startswith("-") and argv[0] not in REMOTE_OPTIONS:
        die(f"hive --node {name}: put the subcommand right after --node NAME, not {argv[0]!r}; "
            "the remote profile comes from the [[nodes]] entry")
    node = find_node(load_nodes(), name)
    cmd = node_argv(node, config.profile_name(), argv)
    try:
        code = subprocess.run(cmd, stdin=subprocess.DEVNULL).returncode
    except FileNotFoundError:
        die("ssh not found on PATH", 1)
    if code == UNREACHABLE:
        die(f"node {name} unreachable: ssh to {node['host']} failed (exit 255); run "
            f"`ssh {node['host']} true` once by hand to check the connection and accept its "
            "host key", 1)
    return code if code >= 0 else 128 - code  # killed by a signal


def cmd_nodes(cfg, args):
    for node in cfg["nodes"]:
        line = (f"node name={quote(node['name'])} host={quote(node['host'])} "
                f"hive={quote(node['hive'])} profile={quote(node['profile'] or 'default')}")
        if node["description"]:
            line += f" description={quote(node['description'])}"
        print(line)
    return 0


def add_parser(sub, name):
    assert name == "nodes"
    sub.add_parser("nodes", help="list the remote nodes ([[nodes]]) that --node reaches",
                   description="List the [[nodes]] entries of config.toml. Run a command on a "
                               "node with `hive --node NAME COMMAND ...` (over ssh, BatchMode).")
