"""The queen dir: what materialize_queen writes for each system."""

import json
import subprocess
import sys
from importlib import resources

import pytest

from hive.drivers import DRIVERS
from hive.queen import materialize_queen

PKG = resources.files("hive").joinpath("queen")


def packaged(path):
    return PKG.joinpath(*path.split("/")).read_bytes()


def test_materialize_claude_composes_instructions(tmp_path):
    materialize_queen({"queen": {"dir": str(tmp_path)}})
    want = (b"<!-- managed by hive; do not edit -->\n" + packaged("queen.md") + b"\n"
            + packaged("claude/rules.md"))
    assert (tmp_path / "CLAUDE.md").read_bytes() == want


def test_materialize_copies_guard_core(tmp_path):
    materialize_queen({"queen": {"dir": str(tmp_path)}})
    hooks = tmp_path / ".claude" / "hooks"
    assert (hooks / "guard_core.py").read_bytes() == packaged("guard_core.py")
    run = subprocess.run(
        [sys.executable, str(hooks / "guard.py")],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "hive list"}}),
        capture_output=True, text=True, env={"CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert (run.returncode, run.stdout, run.stderr) == (0, "", "")


def test_materialize_fake_system(tmp_path, fake_driver, monkeypatch):
    monkeypatch.setattr(fake_driver, "queen_files", {"AGENTS.md": "claude/rules.md"})
    materialize_queen({"queen": {"dir": str(tmp_path), "system": "fake"}})
    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith("<!-- managed by hive; do not edit -->\n")
    assert packaged("queen.md").decode() in text
    assert not (tmp_path / "CLAUDE.md").exists()


def test_materialized_guard_hook_uses_hives_interpreter(tmp_path):
    cfg = {"queen": {"dir": str(tmp_path / "queen")}}
    materialize_queen(cfg)
    path = tmp_path / "queen" / ".claude" / "settings.json"
    got = json.loads(path.read_text())
    want = json.loads(resources.files("hive").joinpath("queen", "claude", "settings.json").read_text())
    hook = got["hooks"]["PreToolUse"][0]["hooks"][0]
    assert hook["command"] == sys.executable
    hook["command"] = "python3"
    assert got == want
    before = path.stat().st_mtime_ns
    materialize_queen(cfg)  # unchanged bytes are not rewritten
    assert path.stat().st_mtime_ns == before


def test_materialize_queen_dies_on_oserror(tmp_path, capsys):
    qdir = tmp_path / "queen"
    qdir.write_text("a file, not a dir")
    with pytest.raises(SystemExit) as exc:
        materialize_queen({"queen": {"dir": str(qdir)}})
    assert exc.value.code == 1 and "cannot write the queen dir" in capsys.readouterr().err


def test_packaged_queen_files_exist():
    for driver in DRIVERS.values():
        for src in driver.queen_files.values():
            assert PKG.joinpath(*src.split("/")).is_file(), src
