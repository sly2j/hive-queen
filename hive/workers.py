"""Workers: `hive list`, and `hive spawn` / `hive stop`, which edit config.toml, then reconcile."""

import json
import re
import shlex
import sys
from pathlib import Path

from hive import sessions, tmux
from hive.activity import pane_map, pane_state, state_fields
from hive.config import (TYPE_RE, ConfigError, check_config_writable, edit_config,
                         expand_config_dir, load_config)
from hive.configedit import ENV_KEY_RE, append_agent, set_indices
from hive.drivers import config_dir_envs, get_driver
from hive.launch import check_launcher_command, check_version
from hive.launchers import check_launcher_type, check_system_arg, launcher_record
from hive.lifecycle import kept_queen, reconcile
from hive.reconcile import (QUEEN_ERROR, RESERVED_TYPES, Existing, New, ResolveError,
                            agent_indices, desired_panes, parse_name, plan, queen_name,
                            resolve_target, sandbox_type)
from hive.trust import TrustError
from hive.util import die, positive_int, quote


def trust_fields(cfg, entry):
    _, path, trusted = get_driver(entry["system"]).trust_state(entry["dir"], entry["config_dir"])
    return f"trusted={'yes' if trusted else 'no'} trust_file={path}"


def cmd_list(cfg, args):
    queen = queen_name(cfg["prefix"])
    up = tmux.session_running(cfg)
    running, unmanaged = tmux.running_panes(cfg) if up else ({}, [])
    print(f"session={cfg['session']} socket={cfg['socket']} running={'yes' if up else 'no'} "
          f"config={cfg['config_path']}")
    print(f"queen name={queen} running={'yes' if queen in running else 'no'} "
          f"dir={cfg['queen']['dir']} {trust_fields(cfg, cfg['queen'])} "
          f"enabled={'yes' if cfg['queen']['enabled'] else 'no'} system={cfg['queen']['system']}")
    for agent in cfg["agents"]:
        n = sum(1 for r in running.values() if r.type == agent["type"])
        print(f"agent type={agent['type']} dir={agent['dir']} count={agent['count']}"
              f"{sparse_field(agent_indices(agent))} "
              f"running={n} command={quote(agent['command'])} "
              f"args={json.dumps(agent['args'])} {trust_fields(cfg, agent)} "
              f"system={agent['system']}"
              + ("" if Path(agent["dir"]).is_dir() else " dir_missing=yes"))
    systems = {"queen": cfg["queen"]["system"], **{a["type"]: a["system"] for a in cfg["agents"]}}
    panes = pane_map(cfg)
    facts = pane_facts(cfg) if running else {}
    for r in running.values():
        screen = tmux.tmux(cfg, "capture-pane", "-p", "-t", r.pane_id, check=False).stdout
        pane = panes.get(r.name)
        system = pane.system if pane else systems.get(r.type, cfg["system"])
        env = {**cfg["env"], **pane.env} if pane else {}
        command, session_id = facts.get(r.pane_id, ("", None))
        state = pane_state(cfg, r.name, system, env, session_id, command, screen)
        kind = get_driver(system).waiting_kind(screen)
        waiting = f" waiting={kind}" if kind else ""
        print(f"pane name={r.name} type={r.type} id={r.pane_id} system={system} "
              f"{state_fields(state)}{waiting}")
    for u in unmanaged:
        print(f"unmanaged pane={u['pane']} window={u['window']} title={quote(u['title'])}")
    for name, kept in sorted(sessions.load(cfg).items()):
        print(f"kept name={name} session={kept['session_id']} "
              f"resume={'pending' if kept.get('resume') is True else 'no'}")
    if up:
        to_start, to_stop = plan(desired_panes(cfg), running, kept_queen(cfg))
        if to_start or to_stop:
            print(f"drift start={','.join(p.name for p in to_start) or 'none'} "
                  f"stop={','.join(r.name for r in to_stop) or 'none'}")
    print(f"search_roots={','.join(cfg['search_roots'])}")
    print(f"discover={cfg['discover'] or ''}")
    return 0


def pane_facts(cfg):
    """{pane_id: (pane_current_command, @hive_session or None)}, in one list-panes call."""
    fmt = "#{pane_id}\t#{pane_current_command}\t#{@hive_session}"
    out = tmux.tmux(cfg, "list-panes", "-s", "-t", "=" + cfg["session"], "-F", fmt)
    facts = {}
    for line in out.stdout.splitlines():
        pane_id, command, session_id = (line.split("\t", 2) + ["", ""])[:3]
        facts[pane_id] = (command, session_id or None)
    return facts


def sparse_field(indices):
    """` indices=2,3` when the instance numbers are not 1..N (D6), else nothing."""
    if indices == list(range(1, len(indices) + 1)):
        return ""
    return f" indices={','.join(map(str, indices))}"


def set_indices_edit(cfg, changes):
    """Write {type: instance numbers} to config.toml in one edit: `count` or `indices`."""
    def edit(text):
        for kind, indices in changes.items():
            text = set_indices(text, kind, indices)
        return text

    def mutate(doc):
        for kind, indices in changes.items():
            entry = next(a for a in doc["agents"] if a["type"] == kind)
            entry.pop("count", None)
            entry.pop("indices", None)
            if sparse_field(sorted(indices)):
                entry["indices"] = sorted(indices)
            else:
                entry["count"] = len(indices)
    edit_config(cfg, edit, mutate)


def report_edit(cfg, kind, old, new):
    """old and new are instance-number lists; new also as `indices=` when sparse."""
    print(f"config agent={kind} count={len(old)}->{len(new)}{sparse_field(sorted(new))} "
          f"file={cfg['config_path']}")


def after_edit(cfg, kind, old, new):
    report_edit(cfg, kind, old, new)
    return reconcile_if_up(cfg)


def reconcile_if_up(cfg):
    if not tmux.session_running(cfg):
        print("session not running; config updated, run 'hive up'")
        return 0
    return reconcile(load_config())


def resolve_or_die(cfg, target, type_override=None):
    try:
        return resolve_target(cfg, target, type_override)
    except ResolveError as e:
        die(str(e), 2)


def parse_env_args(items):
    env = {}
    config_envs = config_dir_envs()
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not ENV_KEY_RE.fullmatch(key):
            die(f"--env '{item}' must be KEY=VALUE with KEY matching {ENV_KEY_RE.pattern}")
        if key in config_envs:
            die(f"--env {key}: {config_envs[key]} (--config-dir or --launcher)")
        env[key] = value
    return env


def ensure_trust(directory, config_dir, seed, system="claude"):
    """Exit 3 unless the pane's trust root is trusted, or --trust records it now."""
    driver = get_driver(system)
    root, path, trusted = driver.trust_state(directory, config_dir)
    if trusted:
        return
    if not seed:
        print(f"untrusted: {directory} (trust root {root}, trust file {path}); "
              "rerun with --trust after the user confirms", file=sys.stderr)
        sys.exit(3)
    try:
        driver.seed_trust(root, config_dir)
    except (TrustError, OSError) as e:
        die(f"cannot record trust for {root}: {e}", 1)
    print(f"trusted {root} in {path}")


def record_args(record, agent_args):
    """Explicit --arg values, else a discover record's optional shell-quoted `args`, else None."""
    if agent_args is not None or "args" not in record:
        return agent_args
    try:
        split = shlex.split(record["args"])
    except ValueError as e:
        die(f"launcher '{record['name']}': args: {e}: {record['args']}", 2)
    if not all(split):
        die(f"launcher '{record['name']}': args: empty argument: {record['args']}", 2)
    return split


def expand_dir_or_none(config_dir):
    return expand_config_dir(config_dir, "config_dir") if config_dir is not None else None


def cmd_spawn(cfg, args):
    if args.resume is not None:
        return spawn_resume(cfg, args)
    command, config_dir, type_name = args.agent_command, args.config_dir, args.type
    agent_args = args.agent_args
    record = None
    if args.system is not None:
        check_system_arg(args.system)
        if args.launcher is not None:
            die("--launcher brings its own system; do not combine it with --system", 2)
    system = args.system  # None: the launcher's, else [defaults] system
    if args.launcher is not None:
        if command is not None or config_dir is not None:
            die("--launcher takes command and config_dir from the launcher; "
                "do not combine it with --command or --config-dir")
        record = getattr(args, "launcher_record", None) or launcher_record(cfg, args.launcher)
        command, config_dir = record["command"], record["config_dir"]
        system = record["system"] or cfg["system"]
        agent_args = record_args(record, agent_args)
        if type_name is None:
            try:
                type_name = sandbox_type(cfg, args.target, args.launcher)
            except ResolveError as e:
                die(str(e))
        check_launcher_type(cfg, type_name, command, expand_dir_or_none(config_dir))
    if command is not None:
        check_launcher_command(command, "--command", system or cfg["system"])
    expanded_dir = expand_dir_or_none(config_dir)
    env = parse_env_args(args.env)
    if args.agent_args is not None and not all(args.agent_args):
        die("--arg must not be empty")
    target = resolve_or_die(cfg, args.target, type_name)
    if (isinstance(target, New) and record is None and command is None and config_dir is None
            and system is None and cfg["default_launcher"]):
        # A new type with no command given runs the default launcher, named after it.
        record = launcher_record(cfg, cfg["default_launcher"])
        command, config_dir = record["command"], record["config_dir"]
        system = record["system"] or cfg["system"]
        check_launcher_command(command, f"launcher '{record['name']}' command", system)
        agent_args = record_args(record, agent_args)
        expanded_dir = expand_dir_or_none(config_dir)
        if type_name is None:
            try:
                type_name = sandbox_type(cfg, args.target, record["name"])
            except ResolveError as e:
                die(str(e))
        check_launcher_type(cfg, type_name, command, expanded_dir)
        target = resolve_or_die(cfg, args.target, type_name)
    if isinstance(target, Existing):
        entry = target.entry
        if system is not None and system != entry["system"]:
            die(f"type '{entry['type']}' runs system '{entry['system']}'; to run another system "
                f"in the same directory give a new type: hive spawn {entry['dir']} "
                "--type <name> --system ...")
        if command is not None and command != entry["command"]:
            die(f"type '{entry['type']}' runs '{entry['command']}'; to run a different command "
                f"in the same directory give a new type: hive spawn {entry['dir']} "
                "--type <name> --command '...'")
        if agent_args is not None and agent_args != entry["args"]:
            die(f"type '{entry['type']}' runs args {json.dumps(entry['args'])}; to run different "
                f"args in the same directory give a new type: hive spawn {entry['dir']} "
                "--type <name> --arg ...", 2)
        if config_dir is not None and expanded_dir != entry["config_dir"]:
            die(f"type '{entry['type']}' has config_dir '{entry['config_dir'] or ''}'; to use "
                f"another one in the same directory give a new type: hive spawn {entry['dir']} "
                "--type <name> ...")
        if args.env is not None and env != entry["env"]:
            die(f"type '{entry['type']}' has a different env; to use another env in the same "
                f"directory give a new type: hive spawn {entry['dir']} --type <name> --env ...")
        if not Path(entry["dir"]).is_dir():
            die(f"type '{entry['type']}' has dir '{entry['dir']}', which does not exist; "
                "fix or remove the entry in config.toml")
        check_config_writable(cfg)
        ensure_trust(entry["dir"], entry["config_dir"], args.trust, entry["system"])
        old = agent_indices(entry)
        new = sorted(old + lowest_free(old, args.n))
        set_indices_edit(cfg, {entry["type"]: new})
        return after_edit(cfg, entry["type"], old, new)

    # The type ends up unquoted in names and commands; keep it to safe characters.
    if target.type in RESERVED_TYPES or not TYPE_RE.fullmatch(target.type):
        suggestion = re.sub(r"[^A-Za-z0-9._-]+", "-", target.type).strip("-") or "agent"
        if suggestion in RESERVED_TYPES:
            suggestion = f"{suggestion}-agent"
        die(f"'{target.type}' is not a usable agent type for '{target.dir}'; "
            "give --type with letters, digits, '.', '_' or '-', e.g. "
            f"--type {suggestion}")
    system = system or cfg["system"]
    try:
        check_version(system, "spawn")
    except ConfigError as e:
        die(str(e), 2)
    if command is None and record is None and system != cfg["system"]:
        command = get_driver(system).default_command  # [defaults] command is the default system's
    write_system = args.system is not None or system != cfg["system"]
    new_agent = {"type": target.type, "dir": target.stored_dir, "count": args.n}
    if command is not None:
        new_agent["command"] = command
    if agent_args is not None:
        new_agent["args"] = agent_args
    if config_dir is not None:
        new_agent["config_dir"] = config_dir
    if write_system:
        new_agent["system"] = system
    if env:
        new_agent["env"] = env
    check_config_writable(cfg)
    ensure_trust(target.dir, expanded_dir, args.trust, system)
    edit_config(cfg,
                lambda text: append_agent(text, target.type, target.stored_dir, args.n,
                                          command, env, config_dir, agent_args,
                                          system if write_system else None),
                lambda doc: doc.setdefault("agents", []).append(new_agent))
    return after_edit(cfg, target.type, [], list(range(1, args.n + 1)))


def spawn_resume(cfg, args):
    """`hive spawn TYPE --resume NAME`: put instance NAME back and launch it into its kept
    session (docs/resume.md)."""
    name = args.resume
    given = [flag for flag, value in (
        ("-n", args.n != 1), ("--type", args.type), ("--command", args.agent_command),
        ("--arg", args.agent_args), ("--config-dir", args.config_dir),
        ("--launcher", args.launcher), ("--system", args.system), ("--env", args.env)) if value]
    if given:
        die(f"--resume restarts one kept instance as configured; do not combine it with "
            f"{', '.join(given)}", 2)
    kept = sessions.load(cfg).get(name)
    if kept is None:
        names = ", ".join(sorted(sessions.load(cfg))) or "none"
        die(f"no kept session for '{name}' (kept: {names}); keep one with "
            "hive stop NAME --keep-session", 2)
    target = resolve_or_die(cfg, args.target)
    if not isinstance(target, Existing):
        die(f"no agent type '{target.type}'; --resume needs the type of '{name}'", 2)
    entry = target.entry
    parsed = parse_name(cfg["prefix"], name)
    if parsed is None or parsed[0] != entry["type"]:
        die(f"'{name}' is not an instance of type '{entry['type']}'", 2)
    old = agent_indices(entry)
    if parsed[1] in old:
        die(f"instance '{name}' is configured already; stop it first: hive stop {name}", 2)
    if not Path(entry["dir"]).is_dir():
        die(f"type '{entry['type']}' has dir '{entry['dir']}', which does not exist; "
            "fix or remove the entry in config.toml")
    check_config_writable(cfg)
    ensure_trust(entry["dir"], entry["config_dir"], args.trust, entry["system"])
    new = sorted(old + [parsed[1]])
    # Mark first: a configured instance without its mark would launch a fresh session.
    try:
        sessions.mark_resume(cfg, name)
    except OSError as e:
        die(f"cannot write {sessions.sessions_file(cfg)}: {e}", 1)
    try:
        set_indices_edit(cfg, {entry["type"]: new})
    except BaseException:
        sessions.record(cfg, {name: kept["session_id"]})  # unmark: the instance stays stopped
        raise
    report_edit(cfg, entry["type"], old, new)
    print(f"resume name={name} session={kept['session_id']}")
    return reconcile_if_up(cfg)


def lowest_free(indices, n):
    """The n lowest instance numbers not in indices (spawn refills holes first)."""
    taken, free, i = set(indices), [], 1
    while len(free) < n:
        if i not in taken:
            free.append(i)
        i += 1
    return free


def is_type(cfg, target):
    return target in RESERVED_TYPES or any(a["type"] == target for a in cfg["agents"])


def is_path(target):
    return "/" in target or target.startswith(("~", "."))


def instance(cfg, name):
    """(entry, N) for the configured instance named `<type>-<machine>-<N>`, else None."""
    parsed = parse_name(cfg["prefix"], name)
    if parsed is None or parsed[0] == "queen":
        return None
    entry = next((a for a in cfg["agents"] if a["type"] == parsed[0]), None)
    return (entry, parsed[1]) if entry and parsed[1] in agent_indices(entry) else None


def stop_type(cfg, args):
    """`hive stop TYPE [-n N | --index N...]`: the entry and the numbers to remove."""
    target = args.targets[0]
    if not (is_type(cfg, target) or is_path(target)):
        die(f"no agent type '{target}'; 'hive list' shows the types")
    entry = resolve_or_die(cfg, target)
    if not isinstance(entry, Existing):
        die(f"no agent type '{entry.type}'; 'hive list' shows the types")
    entry = entry.entry
    current = agent_indices(entry)
    shadowed = instance(cfg, target) if target == entry["type"] else None
    if shadowed:
        print(f"hive: note: '{target}' is a type; to stop instance {shadowed[1]} of type "
              f"'{shadowed[0]['type']}' run: hive stop {shadowed[0]['type']} --index "
              f"{shadowed[1]}", file=sys.stderr)
    if args.index:
        missing = sorted(set(args.index) - set(current))
        if missing:
            die(f"type '{entry['type']}' has no instance {','.join(map(str, missing))} "
                f"(instances: {','.join(map(str, current)) or 'none'})")
        return entry, set(args.index)
    n = args.n or 1
    if n > len(current):
        die(f"type '{entry['type']}' has count {len(current)}; cannot stop {n}")
    return entry, set(current[len(current) - n:])  # the highest indices go first


def cmd_stop(cfg, args):
    if args.n is not None and args.index:
        die("give -n or --index, not both")
    one = args.targets[0] if len(args.targets) == 1 else None
    # D6: a configured type wins, then a configured instance name, then a path.
    if one is not None and (is_type(cfg, one) or (instance(cfg, one) is None and (
            is_path(one) or parse_name(cfg["prefix"], one) is None))):
        entry, remove = stop_type(cfg, args)
        changes = {entry["type"]: remove}
    else:
        if args.n is not None or args.index:
            die("-n and --index take one TYPE target: hive stop TYPE --index N")
        changes = {}
        for name in args.targets:
            hit = instance(cfg, name)
            if is_type(cfg, name) or (hit is None and is_path(name)):
                die(f"'{name}' is a type; give one TYPE (with -n or --index) "
                    "or only instance names")
            if name == queen_name(cfg["prefix"]):
                die(QUEEN_ERROR)
            if hit is None:
                die(f"no instance '{name}'; 'hive list' shows the pane names, "
                    "or run: hive stop TYPE --index N")
            changes.setdefault(hit[0]["type"], set()).add(hit[1])
    entries = {a["type"]: a for a in cfg["agents"]}
    names = [f"{kind}-{cfg['prefix']}-{i}" for kind, remove in changes.items()
             for i in sorted(remove)]
    if args.keep_session:
        for kind in changes:
            msg = get_driver(entries[kind]["system"]).keep_session_msg
            if msg:
                die(f"{msg}; nothing changed. Stop it without --keep-session", 1)
    kept = kept_ids(cfg, names) if args.keep_session else None  # before the panes go
    new = {kind: [i for i in agent_indices(entries[kind]) if i not in remove]
           for kind, remove in changes.items()}
    check_config_writable(cfg)
    try:
        if kept:
            sessions.record(cfg, kept)
        else:
            sessions.forget(cfg, names)
    except OSError as e:
        die(f"cannot write {sessions.sessions_file(cfg)}: {e}", 1)
    set_indices_edit(cfg, new)
    for kind in new:
        report_edit(cfg, kind, agent_indices(entries[kind]), new[kind])
    for name, sid in (kept or {}).items():
        print(f"kept session name={name} session={sid}; resume with: "
              f"hive spawn {parse_name(cfg['prefix'], name)[0]} --resume {name}")
    return reconcile_if_up(cfg)


def kept_ids(cfg, names):
    """{name: session id} for `stop --keep-session`; exit 1 if an instance has none."""
    facts, running = {}, {}
    if tmux.session_running(cfg):
        running, _ = tmux.running_panes(cfg)
        facts = pane_facts(cfg)
    ids = {}
    for name in names:
        pane = running.get(name)
        hive_session = facts.get(pane.pane_id, ("", None))[1] if pane else None
        sid = sessions.current_id(cfg, name, hive_session)
        if sid is None:
            die(f"no session id for {name} (no status file session_id, no running pane with "
                "@hive_session); nothing changed. Stop it without --keep-session", 1)
        ids[name] = sid
    return ids


def add_parser(sub, name):
    if name == "list":
        sub.add_parser("list", help="show config and running state, unmanaged panes, drift")
    elif name == "spawn":
        p = sub.add_parser("spawn", help="add workers (edits config, then reconciles)",
                           description="Add workers: raise the count of an existing agent type, or "
                           "add a new type for a directory. Exit 3 if the directory is untrusted "
                           "(rerun with --trust after the user confirms).")
        p.add_argument("target", metavar="TARGET",
                       help="agent type, or a directory (absolute, ~/..., or a name under search_roots)")
        p.add_argument("-n", type=positive_int, default=1, help="number of workers to add (default 1)")
        p.add_argument("--type", help="agent type name for a new entry (default: directory name, plus "
                       "-<launcher> when a launcher is chosen; letters, digits, '.', '_' and '-' only)")
        p.add_argument("--command", dest="agent_command", metavar="CMD",
                       help="command template; must contain the system's required placeholders and "
                       "tokens (claude: {name} and --remote-control)")
        p.add_argument("--arg", dest="agent_args", action="append", metavar="ARG",
                       help="flag added to the command of a new type (repeatable); "
                            "use --arg=--fable for values starting with '-'")
        p.add_argument("--config-dir", dest="config_dir", metavar="PATH",
                       help="config dir the command uses; only locates the trust file")
        p.add_argument("--launcher", "--sandbox", dest="launcher", metavar="NAME",
                       help="take command and config_dir from launcher NAME (registry, then "
                            "[queen] discover); --sandbox is an alias")
        p.add_argument("--system", metavar="NAME",
                       help="agent system of a new type (default: the launcher's, else "
                            "[defaults] system)")
        p.add_argument("--env", action="append", metavar="KEY=VALUE",
                       help="env for a new type, exported after [env] (repeatable)")
        p.add_argument("--trust", action="store_true",
                       help="record Claude Code workspace trust for the directory (only after the user agreed)")
        p.add_argument("--resume", metavar="NAME",
                       help="put back instance NAME of type TARGET, stopped with --keep-session, "
                            "and launch it into its kept session")
    elif name == "stop":
        p = sub.add_parser("stop", help="remove workers (edits config, then reconciles)",
                           description="Remove workers: N of a type, highest index first, the "
                           "instances --index names, or the instances named "
                           "<type>-<machine>-<N>. A TARGET that is a type is a type.")
        p.add_argument("targets", metavar="TARGET", nargs="+",
                       help="agent type, or one or more instance names")
        p.add_argument("-n", type=positive_int, help="number of workers to remove (default 1)")
        p.add_argument("--index", type=positive_int, action="append", metavar="N",
                       help="remove instance N of TYPE (repeatable)")
        p.add_argument("--keep-session", action="store_true",
                       help="record each removed instance's session id for 'hive spawn TYPE "
                            "--resume NAME'")
