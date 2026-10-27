"""The Codex queen's PreToolUse adapter: guard_core verdicts in Codex's hook protocol."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parent.parent / "hive" / "queen" / "codex" / "hooks" / "guard.py"
CMD = "claude -n {name} --remote-control {name}"


@pytest.fixture
def qdir(tmp_path):
    d = tmp_path / "queen"
    (d / ".codex").mkdir(parents=True)
    (tmp_path / "config.toml").write_text(f'[defaults]\ncommand = "{CMD}"\n')
    return d


def run(qdir, tool, **tool_input):
    payload = {"hook_event_name": "PreToolUse", "cwd": str(qdir), "tool_name": tool,
               "tool_input": tool_input}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=qdir)


def bash(qdir, command):
    return run(qdir, "Bash", command=command)


def patch(qdir, *lines):
    text = "\n".join(["*** Begin Patch", *lines, "+x", "*** End Patch"])
    return run(qdir, "apply_patch", command=text)


def allowed(result):
    return (result.returncode, result.stdout, result.stderr) == (0, "", "")


def denied(result):
    return result.returncode == 2 and result.stdout == "" and result.stderr.startswith("guard:")


def test_codex_adapter_allows_hive_list(qdir):
    assert allowed(bash(qdir, "hive list"))


def test_codex_adapter_denies_chaining(qdir):
    assert denied(bash(qdir, "hive list; ls"))
    assert denied(bash(qdir, "touch /tmp/marker"))


def test_codex_adapter_ask_becomes_deny(qdir):
    result = bash(qdir, "hive down")
    assert denied(result)
    assert result.stderr.strip() == (
        "guard: hive down stops the whole hive, including this queen; codex cannot ask for "
        "confirmation; tell the user to run this by hand: hive down")


@pytest.mark.parametrize("command", [
    'hive spawn x --command "evil {name}"',
    "hive spawn x --arg=--evil",
    "hive spawn x --env A=1",
    "hive spawn x --system opencode",
    "hive spawn x --trust",
    "hive roots add ~/projects",
    'hive launchers add x "claude --remote-control {name}"',
    "hive down",
    "hive restart",
    "hive --node swarm down",
    "hive --node swarm spawn api --trust",
])
def test_codex_adapter_every_ask_is_deny(qdir, command):
    result = bash(qdir, command)
    assert denied(result)
    assert "run this by hand: " + command in result.stderr
    assert "approve to run it" not in result.stderr


def test_codex_adapter_listed_spawn_allowed(qdir):
    assert allowed(bash(qdir, f'hive spawn x --command "{CMD}"'))


def test_codex_adapter_apply_patch_inside_allowed(qdir):
    assert allowed(patch(qdir, "*** Add File: notes.md"))
    assert allowed(run(qdir, "Edit", command="*** Update File: notes.md\n"))


@pytest.mark.parametrize("line", [
    "*** Add File: ../config.toml",
    "*** Update File: /etc/hostname",
    "*** Delete File: secrets/x",
])
def test_codex_adapter_apply_patch_outside_denied(qdir, line):
    assert denied(patch(qdir, line))


@pytest.mark.parametrize("path", ["AGENTS.md", "AGENTS.override.md", ".codex/hooks.json"])
def test_codex_adapter_apply_patch_protected_denied(qdir, path):
    result = patch(qdir, f"*** Update File: {path}")
    assert denied(result) and "hive manages" in result.stderr


@pytest.mark.parametrize("sep", ["\x0b", "\x0c", "\x1c", "\u2028"])
def test_codex_adapter_apply_patch_name_not_split_at_other_line_breaks(qdir, sep):
    assert denied(patch(qdir, f"*** Update File: scratch{sep}/../.codex/hooks/guard.py"))


def test_codex_adapter_apply_patch_move_outside_denied(qdir):
    assert denied(patch(qdir, "*** Update File: notes.md", "*** Move to: ../config.toml"))


def test_codex_adapter_apply_patch_without_file_denied(qdir):
    assert denied(run(qdir, "apply_patch", command="*** Begin Patch\n*** End Patch"))
    assert denied(run(qdir, "apply_patch", command=["x"]))


@pytest.mark.parametrize("tool", ["mcp__x__y", "view_image", "spawn_agent", "web_search", None])
def test_codex_adapter_denies_mcp_and_unknown(qdir, tool):
    assert denied(run(qdir, tool, command="hive list"))


def test_codex_adapter_allows_update_plan(qdir):
    assert allowed(run(qdir, "update_plan", plan=[]))


@pytest.mark.parametrize("stdin", ["", "[]", "not json", '{"tool_name": "Bash"}'])
def test_codex_adapter_malformed_input_blocks(qdir, stdin):
    result = subprocess.run([sys.executable, str(GUARD)], input=stdin, capture_output=True,
                            text=True, cwd=qdir)
    assert denied(result)


def test_codex_adapter_materialized_uses_its_own_dir(tmp_path):
    """Materialized, the queen dir is the script's <qdir>/.codex/hooks parent, not the cwd."""
    hooks = tmp_path / "queen" / ".codex" / "hooks"
    hooks.mkdir(parents=True)
    for name, src in (("guard.py", GUARD), ("guard_core.py", GUARD.parents[2] / "guard_core.py")):
        (hooks / name).write_bytes(src.read_bytes())
    payload = {"tool_name": "apply_patch", "cwd": str(tmp_path),
               "tool_input": {"command": f"*** Add File: {tmp_path / 'notes.md'}\n"}}
    result = subprocess.run([sys.executable, str(hooks / "guard.py")], input=json.dumps(payload),
                            capture_output=True, text=True, cwd=tmp_path)
    assert denied(result) and "outside the queen dir" in result.stderr
