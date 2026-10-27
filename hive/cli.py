"""hive: run N instances of each agent kind in tmux panes.

An agent kind is a directory plus a command. Each kind gets a tmux window,
each instance a pane. All tmux calls go to a dedicated server (tmux -L <socket>).

This module is the command line: the parser, the lock and config policy per command, and
dispatch. Each command lives in the module of its concern (lifecycle, workers, launchers,
roots, config, service).
"""

import argparse
import os
import sys

from hive import config, launchers, lifecycle, lock, nodes, roots, service, workers
from hive.config import ConfigError
from hive.paths import PathError
from hive.util import die, get_version, warn

EPILOG = """\
exit codes:
  0  ok
  1  runtime error, or the session is not running
  2  usage or config error
  3  untrusted or refused (spawn without --trust, dirs/roots refusals)
"""

# Subcommands in help order, each with the module that adds its parser.
COMMANDS = [("up", lifecycle), ("down", lifecycle), ("restart", lifecycle), ("status", lifecycle),
            ("attach", lifecycle), ("list", workers), ("spawn", workers), ("stop", workers),
            ("reconcile", lifecycle), ("launchers", launchers), ("discover", launchers),
            ("dirs", roots), ("roots", roots), ("nodes", nodes), ("inspect-launcher", launchers), ("init", config),
            ("install-service", service), ("uninstall-service", service)]


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hive", description="Run N instances of each agent kind in tmux panes.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"hive {get_version()}")
    parser.add_argument("--profile", metavar="NAME",
                        help="use the named profile <config dir>/hive/profiles/NAME (own config, "
                             "lock, queen dir, tmux socket hive-NAME, unit hive-NAME.service); "
                             "default: $HIVE_PROFILE, else the default profile")
    parser.add_argument("--node", metavar="NAME",
                        help="run the command on the remote hive of [[nodes]] NAME over ssh "
                             "(BatchMode; attach is refused); see hive nodes")
    sub = parser.add_subparsers(dest="command")
    for name, module in COMMANDS:
        module.add_parser(sub, name)
    return parser


LOCKED = ("up", "down", "spawn", "stop", "reconcile", "roots")


def run():
    remote = nodes.split_node_argv(sys.argv[1:])
    if remote is not None:
        # Proxied before any local config or lock: the remote hive parses the command.
        name, config._profile_option, argv = remote
        config.profile_name()
        return nodes.run_remote(name, argv)
    parser = build_parser()
    args = parser.parse_args()
    config._profile_option = args.profile
    config.profile_name()  # an invalid name exits 2 before anything runs
    if args.node is not None:
        die("spell out --node NAME and put it before the subcommand")
    if args.command is None:
        parser.print_help()
        return 2
    if args.command == "init":
        return config.cmd_init(args)
    if args.command == "install-service":
        return service.cmd_install_service(args)
    if args.command == "uninstall-service":
        return service.cmd_uninstall_service(args)
    if args.command in ("down", "status"):
        # These must work with a broken config.toml: systemd's ExecStop runs `down`.
        cfg, problem = config.lenient_config()
        if problem:
            warn(f"config problem: {problem}")
    else:
        cfg = config.load_config()
    if args.command in LOCKED or (args.command == "launchers"
                                  and getattr(args, "launchers_action", None) in ("add", "default")):
        if (args.command == "spawn" and args.launcher is not None
                and args.agent_command is None and args.config_dir is None):
            # discover may be slow: run it before taking the lock.
            args.launcher_record = launchers.launcher_record(cfg, args.launcher)
        lock.hold_lock(required=args.command != "down")
        if args.command != "down":
            cfg = config.load_config()  # fresh copy: another command may have edited it meanwhile
    handlers = {"up": lifecycle.cmd_up, "down": lifecycle.cmd_down,
                "restart": lifecycle.cmd_restart, "status": lifecycle.cmd_status,
                "attach": lifecycle.cmd_attach, "list": workers.cmd_list,
                "spawn": workers.cmd_spawn, "stop": workers.cmd_stop,
                "reconcile": lifecycle.cmd_reconcile, "discover": launchers.cmd_discover,
                "inspect-launcher": launchers.cmd_inspect_launcher, "dirs": roots.cmd_dirs,
                "roots": roots.cmd_roots, "launchers": launchers.cmd_launchers,
                "nodes": nodes.cmd_nodes}
    return handlers[args.command](cfg, args)


def main():
    try:
        return run()
    except KeyboardInterrupt:
        print("hive: interrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        # The reader went away (| head); keep the interpreter's exit flush quiet.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        return 1
    except (ConfigError, PathError) as e:
        die(str(e))


if __name__ == "__main__":
    sys.exit(main())
