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


class FakeDriver:
    """A second system for seam tests: no required tokens, its own config-dir env, no queen."""
    name = "fake"
    default_command = "fake-agent {args}"
    required_tokens = ()
    required_placeholders = ()
    env_scrub = frozenset()
    config_dir_env = "FAKE_HOME"
    config_dir_env_msg = "fake reads FAKE_HOME from its command"
    instructions_file = "AGENTS.md"
    queen_files = {}
    supports_queen = False
    assigns_session_id = False
    binary = "fake-agent"
    min_version = None
    install_hint = "install fake-agent from example.org"
    versions = ("1.0.0",)
    waiting_kinds = ()

    def __init__(self):
        import re
        self.inspect_pattern = re.compile(r"FAKE_HOME")
        self.trust_calls = []

    def trust_state(self, directory, config_dir):
        return directory, None, True

    def seed_trust(self, root, config_dir):
        self.trust_calls.append((root, config_dir))

    def waiting_kind(self, screen):
        return None

    def probe(self, binary):
        from hive.drivers.common import probe_version
        return probe_version(binary)

    def session_args(self, session_id):
        return []

    def resume_args(self, session_id):
        return ["resume", session_id]

    def hook_args(self, hook_cmd, state_file):
        return []

    def poll_state(self, env, session_id):
        return None

    def prepare_launch(self, env, pane):
        return None

    def queen_extras(self, command, args=()):
        return command


@pytest.fixture
def fake_driver(monkeypatch):
    """Register FakeDriver as system "fake" for one test."""
    from hive import drivers
    driver = FakeDriver()
    monkeypatch.setitem(drivers.DRIVERS, "fake", driver)
    return driver
