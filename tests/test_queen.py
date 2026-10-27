"""The queen dir: what materialize_queen writes for each system."""

import json
import subprocess
import sys
import tomllib
from importlib import resources
from pathlib import Path

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


def test_materialize_codex_queen(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    qdir = tmp_path / "queen"
    materialize_queen({"queen": {"dir": str(qdir), "system": "codex"}, "profile": "test"})
    files = sorted(str(p.relative_to(qdir)) for p in qdir.rglob("*") if p.is_file())
    assert files == [".codex/config.toml", ".codex/hooks.json", ".codex/hooks/guard.py",
                     ".codex/hooks/guard_core.py", "AGENTS.md"]
    assert (qdir / "AGENTS.md").read_bytes() == (
        b"<!-- managed by hive; do not edit -->\n" + packaged("queen.md") + b"\n"
        + packaged("codex/rules.md"))
    hooks = json.loads((qdir / ".codex" / "hooks.json").read_text())
    hook = hooks["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == ".*"
    guard = qdir / ".codex" / "hooks" / "guard.py"
    assert hook["hooks"][0]["command"] == f"{sys.executable} {guard}"
    config = tomllib.loads((qdir / ".codex" / "config.toml").read_text())
    assert config["web_search"] == "disabled"
    assert config["features"]["unified_exec"] is False
    assert config["shell_environment_policy"]["set"] == {
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HIVE_PROFILE": "test"}
    run = subprocess.run(
        [sys.executable, str(guard)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "hive list"}}),
        capture_output=True, text=True, cwd=tmp_path)
    assert (run.returncode, run.stdout, run.stderr) == (0, "", "")


def test_materialize_codex_default_profile_named_default(tmp_path, monkeypatch):
    """The daemon may carry a test hive's HIVE_PROFILE; the default queen names its own."""
    monkeypatch.setenv("PATH", "/h\u00e9/\U0001f600/bin:/bin")
    materialize_queen({"queen": {"dir": str(tmp_path), "system": "codex"}, "profile": None})
    config = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    env = config["shell_environment_policy"]["set"]
    assert env["HIVE_PROFILE"] == "default"
    assert env["PATH"].endswith(":/h\u00e9/\U0001f600/bin:/bin")
    hooks = tmp_path / ".codex" / "hooks.json"
    before = hooks.read_bytes()
    materialize_queen({"queen": {"dir": str(tmp_path), "system": "codex"}, "profile": None})
    assert hooks.read_bytes() == before  # same bytes: Codex keeps its hook trust
