#!/usr/bin/env python3
"""PreToolUse adapter for the hive queen on Claude Code. Managed by hive; do not edit.

A thin adapter: the rules live in guard_core.py (the sibling copy materialized next to this
file, or hive/queen/guard_core.py in the repo layout), which returns a verdict; this file only
knows Claude's tool names and protocol. Only the QUEEN_TOOLS are allowed; any other tool
(WebFetch, Agent, mcp__*, ...) is denied. Bash and Monitor: only a single `hive ...` command
(optionally `hive --node NAME ...`, checked like the command it runs remotely), no chaining,
redirection or substitution, and no argument under a secrets/private path. Of those,
`hive spawn --command X` (also `--command=X` and argparse abbreviations such as `--comm`) runs
without a prompt only when X is a command string from ../config.toml ([defaults] command or an
[[agents]] command). Likewise each `--arg X` (same forms) must be an args string from
[defaults], [queen] or an [[agents]] entry. `--system X` must name a system in config.toml. For
any other --command, --arg or --system, for any spawn `--env` or `--trust` (same
abbreviations), for `hive roots add PATH`, for `hive launchers add` and for
`hive down`/`restart`, the guard answers "ask" so the user confirms (`hive stop` needs no
prompt). Read, Grep, Glob, Edit, Write, NotebookEdit: only paths inside the queen dir
($CLAUDE_PROJECT_DIR), never under a secrets/private path, no `..` in glob patterns, and no
writes into its .claude dir, .mcp.json, .claude.json or CLAUDE.md. AskUserQuestion is allowed
as is. Exit 2 blocks the tool call (deny wins over ask); "ask" is JSON on stdout with exit 0;
any error blocks (fail closed).
"""

import json
import os
import sys
from pathlib import Path

here = Path(__file__).resolve()
# `import guard_core` finds the sibling copy (the script's own dir is sys.path[0]). Only in the
# repo layout (not a materialized .claude dir, no sibling) fall back to hive/queen; never put the
# queen dir on the path, the queen can write files there.
if not (here.parent / "guard_core.py").exists() and here.parents[1].name != ".claude":
    sys.path.append(str(here.parents[2]))
try:
    import guard_core
except Exception as e:  # fail closed, without relying on guard_core
    print(f"guard: cannot load guard_core, blocking: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(2)

SHELL_TOOLS = {"Bash", "Monitor"}
FILE_TOOLS = {"Read", "Grep", "Glob", "Edit", "Write", "NotebookEdit"}
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
# Asks the user a question; no input the guard needs to check.
DIALOG_TOOLS = {"AskUserQuestion"}
QUEEN_TOOLS = {"Bash", "Monitor", "Read", "Grep", "Glob", "Edit", "Write", "NotebookEdit"} | DIALOG_TOOLS
PROTECTED_NAMES = (".claude", ".mcp.json", ".claude.json", "CLAUDE.md")


def block(reason):
    print(reason, file=sys.stderr)
    sys.exit(2)


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            block("guard: hook input is not a JSON object")
        tool = data.get("tool_name")
        tool_input = data.get("tool_input")
        if tool not in QUEEN_TOOLS:
            block(f"guard: tool {tool!r} is not available to the queen")
        if not isinstance(tool_input, dict):
            block("guard: tool_input is not an object")
        qdir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
        if tool in DIALOG_TOOLS:
            return 0
        if tool in SHELL_TOOLS:
            verdict = guard_core.check_bash(tool_input.get("command"), qdir)
        else:
            verdict = guard_core.check_file_tool(tool, tool_input, qdir, PROTECTED_NAMES)
        if verdict.decision == "deny":
            block(verdict.reason)
        if verdict.decision == "ask":
            ask(verdict.reason)
        return 0
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block(f"guard: error, blocking: {type(e).__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())
