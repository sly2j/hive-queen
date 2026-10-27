#!/usr/bin/env python3
"""PreToolUse adapter for the hive queen on Codex. Managed by hive; do not edit.

A thin adapter: the rules live in guard_core.py (the sibling copy materialized next to this
file, or hive/queen/guard_core.py in the repo layout), which returns a verdict; this file only
knows Codex's tool names and protocol. Codex runs it from the project hooks file
<queen dir>/.codex/hooks.json for every tool call (matcher ".*").

- Bash (the shell tool; `tool_input.command` a string): checked by guard_core.check_bash, so
  only a single `hive ...` command runs. Codex hooks cannot ask the user, so every "ask"
  verdict (hive down, spawn --trust, an unlisted --command, ...) becomes a deny whose reason
  names the command for the user to run by hand.
- apply_patch (also matched as Edit or Write; the patch text in `tool_input.command`): every
  path of an `*** Add File:`, `*** Update File:`, `*** Delete File:` or `*** Move to:` line is
  checked as a write inside the queen dir, never into AGENTS.md, AGENTS.override.md or .codex.
- update_plan is allowed (no side effect); every other tool (mcp__*, spawn_agent, view_image,
  unknown) is denied.

A deny is exit 2 with the reason on stderr; any error blocks (fail closed).
"""

import json
import os
import re
import sys
from pathlib import Path

here = Path(__file__).resolve()
# `import guard_core` finds the sibling copy (the script's own dir is sys.path[0]). Only in the
# repo layout (not a materialized .codex dir, no sibling) fall back to hive/queen; never put the
# queen dir on the path, the queen can write files there.
if not (here.parent / "guard_core.py").exists() and here.parents[1].name != ".codex":
    sys.path.append(str(here.parents[2]))
try:
    import guard_core
except Exception as e:  # fail closed, without relying on guard_core
    print(f"guard: cannot load guard_core, blocking: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(2)

SHELL_TOOLS = {"Bash"}
PATCH_TOOLS = {"apply_patch", "Edit", "Write"}
ALLOWED_TOOLS = {"update_plan"}
PROTECTED_NAMES = ("AGENTS.md", "AGENTS.override.md", ".codex")
PATCH_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.*)$")


def block(reason):
    print(reason, file=sys.stderr)
    sys.exit(2)


def queen_dir(data):
    """The materialized queen dir (<qdir>/.codex/hooks/guard.py), else the session cwd."""
    if here.parents[1].name == ".codex":
        return here.parents[2]
    return Path(data.get("cwd") or os.getcwd()).resolve()


def patch_paths(patch):
    if not isinstance(patch, str):
        block("guard: apply_patch input has no patch text")
    # Split on "\n" only: splitlines() also breaks at \v, \f, \x1c and others, which may be
    # part of a file name, and would check a truncated path.
    paths = [m.group(1).strip() for line in patch.split("\n")
             if (m := PATCH_PATH.match(line.rstrip("\r")))]
    if not paths:
        block("guard: apply_patch names no file")
    return paths


def main():
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            block("guard: hook input is not a JSON object")
        tool = data.get("tool_name")
        tool_input = data.get("tool_input")
        if tool in ALLOWED_TOOLS:
            return 0
        if tool not in SHELL_TOOLS | PATCH_TOOLS:
            block(f"guard: tool {tool!r} is not available to the queen")
        if not isinstance(tool_input, dict):
            block("guard: tool_input is not an object")
        qdir = queen_dir(data)
        command = tool_input.get("command")
        if tool in SHELL_TOOLS:
            verdict = guard_core.check_bash(command, qdir)
            if verdict.decision == "ask":
                block(f"guard: {verdict.reason.removesuffix('; approve to run it')}; codex "
                      f"cannot ask for confirmation; tell the user to run this by hand: {command}")
        else:
            for path in patch_paths(command):
                verdict = guard_core.check_path(path, qdir, True, PROTECTED_NAMES)
                if verdict.decision != "allow":
                    break
        if verdict.decision != "allow":
            block(verdict.reason)
        return 0
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block(f"guard: error, blocking: {type(e).__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())
