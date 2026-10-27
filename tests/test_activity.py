import json
import sys
from pathlib import Path

import pytest

import hive.drivers
from hive import activity
from hive.activity import State, pane_state, state_fields, tmux_fallback


class PollDriver:
    def __init__(self, result):
        self.result = result

    def poll_state(self, env, session_id):
        return self.result


@pytest.fixture
def cfg(tmp_path):
    return {"state_dir": str(tmp_path / "state"), "pane_shell": None}


@pytest.fixture
def use_driver(monkeypatch):
    def _use(result):
        monkeypatch.setitem(hive.drivers.DRIVERS, "t", PollDriver(result))
    return _use


def call(cfg, now, command="claude", screen="s", name="p"):
    return pane_state(cfg, name, "t", {}, "sid", command, screen, now=now)


def write_status(cfg, name, **data):
    activity.write_json(activity.status_file(cfg, name), data)


def test_pane_state_prefers_hook_file_over_tmux(cfg, use_driver):
    use_driver(None)
    write_status(cfg, "p", state="done", ts=958.0)
    assert call(cfg, 1000.0, command="bash") == State("done", "hook", 42)


def test_pane_state_poll_wins_over_file(cfg, use_driver):
    use_driver("busy")
    write_status(cfg, "p", state="done", ts=900.0)
    assert call(cfg, 1000.0) == State("busy", "api", 0)


def test_tmux_fallback_first_sight(cfg, use_driver):
    use_driver(None)
    assert call(cfg, 1000.0) == State("busy", "tmux", 0)


def test_tmux_fallback_quiet(cfg, use_driver):
    use_driver(None)
    call(cfg, 1000.0)
    assert call(cfg, 1030.0) == State("quiet", "tmux", 30)


def test_tmux_fallback_changed_screen_resets_since(cfg, use_driver):
    use_driver(None)
    call(cfg, 1000.0, screen="a")
    assert call(cfg, 1030.0, screen="b") == State("busy", "tmux", 0)
    assert call(cfg, 1040.0, screen="b") == State("busy", "tmux", 10)


def test_tmux_fallback_dead(cfg):
    assert tmux_fallback(cfg, "p", "bash", "s", 1000.0).state == "dead"


def test_tmux_fallback_pane_shell_basename_is_dead(cfg):
    cfg["pane_shell"] = "/usr/bin/zsh -l"
    assert tmux_fallback(cfg, "p", "zsh", "s", 1000.0).state == "dead"
    assert tmux_fallback(cfg, "p", "claude", "s", 1000.0).state == "busy"


def test_reset_status_removes_both_files(cfg):
    write_status(cfg, "p", state="done", ts=1.0)
    tmux_fallback(cfg, "p", "claude", "s", 1000.0)
    assert activity.status_file(cfg, "p").exists() and activity.screen_file(cfg, "p").exists()
    activity.reset_status(cfg, "p")
    assert not activity.status_file(cfg, "p").exists()
    assert not activity.screen_file(cfg, "p").exists()


def test_state_fields_format():
    assert state_fields(State("done", "hook", 42)) == "state=done source=hook age=42"


def test_hook_cmd_uses_sys_executable_and_packaged_script():
    argv = activity.hook_cmd()
    assert argv[0] == sys.executable
    assert Path(argv[1]).as_posix().endswith("hive/hooks/status_hook.py")


def test_pane_map_includes_queen_and_is_empty_for_lenient_cfg(tmp_path, monkeypatch):
    from hive.config import parse_config
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "hive" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('prefix = "t"\n\n[defaults]\ncommand = "claude -n {name} --remote-control {name}"\n')
    cfg = parse_config()
    assert "hive-queen-t" in activity.pane_map(cfg)
    assert activity.pane_map({"state_dir": "x"}) == {}
