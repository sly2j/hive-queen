"""Launchers: the [[launchers]] registry, `[queen] discover` records, inspect-launcher."""

import subprocess
import sys

from hive.config import LAUNCHER_NAME_RE, edit_config, expand_config_dir
from hive.configedit import append_launcher, set_default_launcher
from hive.inspect import LauncherError, inspect_launcher, resolve_launcher
from hive.launch import check_launcher_command
from hive.reconcile import ResolveError, parse_records
from hive.util import die, quote

DISCOVER_TIMEOUT = 60


def run_discover(cfg):
    """Run `[queen] discover`: (records, error message, exit code); records is None on error."""
    try:
        out = subprocess.run(cfg["discover"], shell=True, capture_output=True, text=True,
                             timeout=DISCOVER_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, f"discover command timed out after {DISCOVER_TIMEOUT}s: {cfg['discover']}", 1
    if out.returncode != 0:
        return None, f"discover command failed (exit {out.returncode}): {out.stderr.strip()}", 1
    try:
        return parse_records(out.stdout), None, 0
    except ResolveError as e:
        return None, str(e), 2


def all_launchers(cfg):
    """(registry records, then discover records; discover error or None). Never raises on discover."""
    records = [{"name": l["name"], "source": "config", "config_dir": l["config_dir"],
                "command": l["command"], "description": l["description"], "shadowed": False}
               for l in cfg["launchers"]]
    if not cfg["discover"]:
        return records, None
    found, error, _ = run_discover(cfg)
    if error is not None:
        return records, error
    registry = {r["name"] for r in records}
    for r in found:
        records.append({"name": r["name"], "source": "discover", "config_dir": r["config_dir"] or None,
                        "command": r["command"], "description": r.get("description"),
                        "shadowed": r["name"] in registry})
    return records, None


def launcher_record(cfg, name):
    """The launcher called `name`: the registry first, then the `[queen] discover` records."""
    for l in cfg["launchers"]:
        if l["name"] == name:
            return {"name": name, "command": l["command"], "config_dir": l["config_dir"]}
    known = [l["name"] for l in cfg["launchers"]]
    if cfg["discover"]:
        records, error, code = run_discover(cfg)
        if error is not None:
            die(error, code)
        for record in records:
            if record["name"] == name:
                return {**record, "config_dir": record["config_dir"] or None}
        known += [r["name"] for r in records if r["name"] not in known]
    die(f"no launcher '{name}'; available: {', '.join(known) or 'none'}", 2)


def check_launcher_type(cfg, type_name, command, config_dir):
    """Refuse a launcher whose suffixed type is already taken by a different command or config dir."""
    for entry in cfg["agents"]:
        if entry["type"] == type_name and (entry["command"] != command
                                           or entry["config_dir"] != config_dir):
            die(f"type '{type_name}' already exists for '{entry['dir']}' and runs "
                f"'{entry['command']}'; the launcher's command differs. Give --type <name> "
                "to start it under another type")


def cmd_launchers(cfg, args):
    action = getattr(args, "launchers_action", None) or "list"
    return {"list": launchers_list, "add": launchers_add, "default": launchers_default}[action](cfg, args)


def launchers_add(cfg, args):
    name = args.name
    if not LAUNCHER_NAME_RE.fullmatch(name):
        die(f"launcher name '{name}' must match {LAUNCHER_NAME_RE.pattern}", 2)
    records, error = all_launchers(cfg)
    if error is not None:
        print(f"warning: discover failed, collisions with its records are not checked: {error}",
              file=sys.stderr)
    if any(r["name"] == name for r in records):
        die(f"launcher '{name}' already exists; names must be unique across the registry and discover", 2)
    check_launcher_command(args.launch_command, "COMMAND", cfg["system"])
    try:
        resolve_launcher(args.launch_command)
    except LauncherError as e:
        label = "refused" if e.code == 3 else "not found"
        print(f"{label}: {e}", file=sys.stderr)
        return e.code
    config_dir = (expand_config_dir(args.config_dir, "--config-dir")
                  if args.config_dir is not None else None)
    first = cfg["default_launcher"] is None

    def edit(text):
        text = append_launcher(text, name, args.launch_command, config_dir, args.description)
        return set_default_launcher(text, name) if first else text

    def mutate(doc):
        launcher = {"name": name, "command": args.launch_command}
        if config_dir is not None:
            launcher["config_dir"] = config_dir
        if args.description is not None:
            launcher["description"] = args.description
        doc.setdefault("launchers", []).append(launcher)
        if first:
            doc.setdefault("defaults", {})["launcher"] = name

    edit_config(cfg, edit, mutate)
    print(f"launcher added name={quote(name)} default={'yes' if first else 'no'} file={cfg['config_path']}")
    return 0


def launchers_default(cfg, args):
    records, error = all_launchers(cfg)
    names = list(dict.fromkeys(r["name"] for r in records))
    if args.name not in names:
        if error is not None:
            print(f"warning: discover failed: {error}", file=sys.stderr)
        die(f"no launcher '{args.name}'; available: {', '.join(names) or 'none'}", 2)
    edit_config(cfg, lambda text: set_default_launcher(text, args.name),
                lambda doc: doc.setdefault("defaults", {}).__setitem__("launcher", args.name))
    print(f"default launcher={quote(args.name)} file={cfg['config_path']}")
    return 0


def launchers_list(cfg, args):
    records, error = all_launchers(cfg)
    default = cfg["default_launcher"]

    def is_default(r):
        return r["name"] == default and not r["shadowed"]

    # Stable sort: the default first, then registry, then discover, each in source order.
    for r in sorted(records, key=lambda r: not is_default(r)):
        line = (f"launcher name={quote(r['name'])} source={r['source']} "
                f"default={'yes' if is_default(r) else 'no'} "
                f"config_dir={quote(r['config_dir'] or 'default')} command={quote(r['command'])}")
        if r["description"]:
            line += f" description={quote(r['description'])}"
        if r["shadowed"]:
            line += " shadowed=yes"
        print(line)
    if error is not None:
        print(f"discover error={quote(error)}")
    return 0


def cmd_discover(cfg, args):
    if not cfg["discover"]:
        die("no discover command configured; set [queen] discover", 2)
    return subprocess.run(cfg["discover"], shell=True).returncode


def cmd_inspect_launcher(cfg, args):
    return inspect_launcher(args.launch_command, cfg["inspect_roots"], sys.stdout, sys.stderr)


def add_parser(sub, name):
    if name == "launchers":
        p = sub.add_parser("launchers", help="list the launcher registry and discover records")
        launchers_sub = p.add_subparsers(dest="launchers_action")
        launchers_sub.add_parser("list", help="list launchers (default action)")
        lp = launchers_sub.add_parser("add", help="register a launcher in config.toml (never runs it)")
        lp.add_argument("name", metavar="NAME")
        lp.add_argument("launch_command", metavar="COMMAND", help="the full launch command, as one argument")
        lp.add_argument("--config-dir", metavar="PATH", help="CLAUDE_CONFIG_DIR the launcher uses")
        lp.add_argument("--description", metavar="TEXT")
        lp = launchers_sub.add_parser("default", help="set the default launcher (edits config)")
        lp.add_argument("name", metavar="NAME")
    elif name == "discover":
        sub.add_parser("discover", help="run [queen] discover and print its output")
    elif name == "inspect-launcher":
        p = sub.add_parser("inspect-launcher",
                           help="read-only: show a launcher's CLAUDE_CONFIG_DIR evidence (files under inspect_roots only)")
        p.add_argument("launch_command", metavar="COMMAND", help="the full launch command, as one argument")
