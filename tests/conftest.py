"""Isolation for every test: a temp HOME and XDG_CONFIG_HOME, no Claude config dir, no tmux client env.

hive's default tmux socket is the user's live hive; tests must never reach it or the real
config. Tests that need their own paths override these with monkeypatch or an env dict.
TMUX_TMPDIR points at a private dir, so even a socket named "hive" is a different server.
"""

import shutil
import tempfile

import pytest


@pytest.fixture(scope="session")
def _tmux_tmpdir():
    # Short path under /tmp: tmux socket paths have a ~100 byte limit (macOS temp dirs are long).
    path = tempfile.mkdtemp(prefix="hive-t-", dir="/tmp")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolate(tmp_path_factory, monkeypatch, _tmux_tmpdir):
    base = tmp_path_factory.mktemp("isolated")
    (base / "home").mkdir()
    monkeypatch.setenv("HOME", str(base / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base / "xdg"))
    monkeypatch.setenv("TMUX_TMPDIR", _tmux_tmpdir)
    for name in ("CLAUDE_CONFIG_DIR", "TMUX", "TMUX_PANE", "HIVE_PROFILE"):
        monkeypatch.delenv(name, raising=False)
