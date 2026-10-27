"""search_roots: `hive dirs` (read-only listing) and `hive roots` (list, add, remove)."""

import argparse
import os
import sys
from pathlib import Path

from hive.config import edit_config, read_config
from hive.configedit import set_search_roots
from hive.dirs import MAX_DEPTH, PRIVATE_NAMES, list_dirs
from hive.paths import expanduser, secret_check_parts
from hive.util import die, positive_int


def depth_int(text):
    value = positive_int(text)
    if value > MAX_DEPTH:
        raise argparse.ArgumentTypeError(f"must be <= {MAX_DEPTH}")
    return value


def cmd_dirs(cfg, args):
    return list_dirs(cfg, args.root, args.depth, sys.stdout, sys.stderr)


def same_dir(text, resolved):
    path = expanduser(text).resolve()
    if path == resolved:
        return True
    if sys.platform == "darwin":  # case-insensitive APFS: compare by file identity
        try:
            return os.path.samefile(path, resolved)
        except OSError:
            pass
    return False


def cmd_roots(cfg, args):
    if args.action is None:
        if args.path is not None:
            die("hive roots takes 'add PATH' or 'remove PATH'")
        for r in cfg["search_roots"]:
            print(f"root={Path(r).absolute()}")
        if not cfg["search_roots"]:
            print("roots=none")
        return 0
    if args.path is None:
        die(f"hive roots {args.action} needs a PATH")
    raw = read_config(Path(cfg["config_path"])).get("search_roots", [])
    resolved = expanduser(args.path).resolve()
    if args.action == "remove":
        i = next((i for i, r in enumerate(raw) if same_dir(r, resolved)), None)
        if i is None:
            print(f"not found: {resolved} is not in search_roots", file=sys.stderr)
            return 2
        edit_config(cfg, lambda text: set_search_roots(text, raw[:i] + raw[i + 1:]),
                    lambda doc: doc["search_roots"].pop(i))
        print(f"removed {raw[i]}")
        return 0
    given = expanduser(args.path)
    parts = (*secret_check_parts(given), *secret_check_parts(resolved))
    if any(p.lower() in PRIVATE_NAMES for p in parts):
        print(f"refused: {resolved} is under a secrets/private path", file=sys.stderr)
        return 3
    if not resolved.is_dir():
        die(f"'{args.path}' is not an existing directory")
    if any(same_dir(r, resolved) for r in raw):
        print("unchanged")
        return 0
    spelling = os.path.normpath(args.path) if args.path.startswith("~") else str(resolved)
    edit_config(cfg, lambda text: set_search_roots(text, [*raw, spelling]),
                lambda doc: doc.setdefault("search_roots", []).append(spelling))
    print(f"added {spelling}")
    return 0


def add_parser(sub, name):
    if name == "dirs":
        p = sub.add_parser("dirs", help="read-only: list directories under search_roots")
        p.add_argument("root", metavar="ROOT", nargs="?",
                       help="a search root, a directory inside one, or a name as for spawn")
        p.add_argument("--depth", type=depth_int, default=1, metavar="N",
                       help=f"levels to list (default 1, max {MAX_DEPTH})")
    elif name == "roots":
        p = sub.add_parser("roots", help="show search_roots, or add/remove one (edits config)")
        p.add_argument("action", nargs="?", choices=["add", "remove"],
                       help="add or remove a search root; omit to list them")
        p.add_argument("path", nargs="?", metavar="PATH",
                       help="the directory to add or remove (required with an action)")
