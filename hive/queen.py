"""The queen dir: the packaged queen files, written for the queen's system."""

import json
import sys
from importlib import resources
from pathlib import Path

from hive.drivers import get_driver
from hive.util import die

QUEEN_HEADER = "<!-- managed by hive; do not edit -->\n"


def queen_settings(src):
    """Packaged settings.json with the guard hook run by hive's own interpreter.

    A bare python3 may be older than 3.11 (stock macOS) and lack tomllib, which would
    silently disable the guard.
    """
    settings = json.loads(src.read_bytes())
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        for hook in entry.get("hooks", []):
            if hook.get("command") == "python3":
                hook["command"] = sys.executable or "python3"
    return (json.dumps(settings, indent=2) + "\n").encode()


# Packaged src path -> renderer(source) for files that are not copied byte for byte.
# A system with its own rendered file adds an entry here.
RENDERERS = {"claude/settings.json": queen_settings}


def compose_instructions(pkg, src):
    """The instructions file: header, the common body, then the system's own rules."""
    return (QUEEN_HEADER.encode() + pkg.joinpath("queen.md").read_bytes() + b"\n"
            + pkg.joinpath(*src.split("/")).read_bytes())


def materialize_queen(cfg):
    """Write the packaged queen instructions into the queen dir when missing or different."""
    driver = get_driver(cfg["queen"].get("system", "claude"))
    qdir = Path(cfg["queen"]["dir"])
    try:
        pkg = resources.files("hive").joinpath("queen")
        files = {}
        for dest, src in driver.queen_files.items():
            source = pkg.joinpath(*src.split("/"))
            if dest == driver.instructions_file:
                data = compose_instructions(pkg, src)
            elif src in RENDERERS:
                data = RENDERERS[src](source)
            else:
                data = source.read_bytes()
            files[qdir / dest] = data
            (qdir / dest).parent.mkdir(parents=True, exist_ok=True)
        for path, data in files.items():
            if not path.exists() or path.read_bytes() != data:
                path.write_bytes(data)
    except OSError as e:
        die(f"cannot write the queen dir {qdir}: {e.strerror or e}", 1)
