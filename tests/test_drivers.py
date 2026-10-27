import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from hive.config import load_config
from hive.drivers import config_dir_envs, get_driver
from hive.drivers import common
from hive.launch import check_launcher_command, check_version, preflight, warn_untrusted
from hive.util import ConfigError

claude = get_driver("claude")

TRUST = "Do you trust the files in this folder?\n  1. Yes, I trust this folder"
THEME = "Welcome\n Choose the text style\nthat looks best with your terminal"
LOGIN = "Select login method:\n 1. Claude account"


def test_session_args_claude():
    assert claude.session_args("abc") == ["--session-id", "abc"]


def test_resume_args_claude():
    assert claude.resume_args("abc") == ["--resume", "abc"]


def test_hook_args_claude():
    args = claude.hook_args(["python3", "/x y/hook.py"], "/tmp/state.json")
    assert args[0] == "--settings"
    hooks = json.loads(args[1])["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "Stop", "StopFailure",
                          "Notification", "SessionEnd"}
    for ev, entries in hooks.items():
        (entry,) = entries
        expected = shlex.join(["python3", "/x y/hook.py", "/tmp/state.json", "--event", ev])
        assert entry["hooks"] == [{"type": "command", "command": expected}]
        assert entry.get("matcher") == ("permission_prompt|idle_prompt|agent_needs_input"
                                        if ev == "Notification" else None)


def test_poll_state_claude():
    assert claude.poll_state({}, "abc") is None


def test_waiting_kind_theme():
    assert claude.waiting_kind(THEME) == "theme"


def test_waiting_kind_login():
    assert claude.waiting_kind(LOGIN) == "login"


def test_waiting_kind_trust():
    assert claude.waiting_kind(TRUST) == "trust"
    assert claude.waiting_kind("i trust this\n  FOLDER") == "trust"


def test_waiting_kind_none():
    assert claude.waiting_kind("> hello\n  ? for shortcuts") is None
    assert claude.waiting_kind("we should talk about whether to trust this folder") is None


def fake_run(monkeypatch, stdout="", stderr="", exc=None):
    def run(cmd, **kw):
        assert cmd[1:] == ["--version"] and kw.get("timeout")
        if exc:
            raise exc
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=0)
    monkeypatch.setattr(common.subprocess, "run", run)


def test_probe_parses_claude(monkeypatch):
    fake_run(monkeypatch, stdout="2.1.311 (Claude Code)\n")
    assert claude.probe("claude") == "2.1.311"
    fake_run(monkeypatch, stdout="opencode v2.2.0\n")
    assert claude.probe("opencode") == "2.2.0"
    fake_run(monkeypatch, stderr="v1.0.5")
    assert claude.probe("x") == "1.0.5"
    fake_run(monkeypatch, stdout="no version here")
    assert claude.probe("x") is None
    fake_run(monkeypatch, exc=FileNotFoundError())
    assert claude.probe("missing") is None
    fake_run(monkeypatch, exc=subprocess.TimeoutExpired("x", 10))
    assert claude.probe("slow") is None


def test_get_driver_unknown(tmp_path, monkeypatch, capsys):
    with pytest.raises(ValueError, match="nope"):
        get_driver("nope")
    cfg = tmp_path / "xdg" / "hive" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('prefix = "t"\n\n[defaults]\nsystem = "nope"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    with pytest.raises(SystemExit) as exc:
        load_config()
    assert exc.value.code == 2


def test_prepare_launch_claude_none():
    assert claude.prepare_launch({}, "t-1") is None
    assert claude.assigns_session_id is True


def test_get_driver_known_but_unregistered(tmp_path, monkeypatch, capsys):
    with pytest.raises(ValueError, match="system 'opencode' is not in this release"):
        get_driver("opencode")
    cfg = tmp_path / "xdg" / "hive" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('prefix = "t"\n\n[defaults]\nsystem = "opencode"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    with pytest.raises(SystemExit) as exc:
        load_config()
    assert exc.value.code == 2
    assert "is not in this release" in capsys.readouterr().err


def test_get_driver_unknown_text():
    with pytest.raises(ValueError, match=r"unknown system 'nope' \(known: claude, codex\)"):
        get_driver("nope")


def test_config_dir_envs(fake_driver):
    envs = config_dir_envs()
    assert envs["FAKE_HOME"] == fake_driver.config_dir_env_msg
    assert "CLAUDE_CONFIG_DIR" in envs


def fake_binary(tmp_path, output="fake 1.0.0"):
    path = tmp_path / "fake-agent"
    path.write_text(f"#!/bin/sh\necho '{output}'\n")
    path.chmod(0o755)
    return str(path)


def test_probe_below_min_version(fake_driver, tmp_path, monkeypatch):
    monkeypatch.setattr(fake_driver, "min_version", (9, 0, 0))
    monkeypatch.setattr(fake_driver, "binary", fake_binary(tmp_path))
    with pytest.raises(ConfigError) as exc:
        check_version("fake", "queen")
    text = str(exc.value)
    assert "1.0.0 is older than 9.0.0" in text
    assert fake_driver.install_hint in text


def test_probe_ok(fake_driver, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fake_driver, "min_version", (1, 0, 0))
    monkeypatch.setattr(fake_driver, "binary", fake_binary(tmp_path))
    check_version("fake", "queen")
    assert capsys.readouterr().err == ""


def test_probe_binary_missing(fake_driver, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fake_driver, "min_version", (1, 0, 0))
    monkeypatch.setattr(fake_driver, "binary", str(tmp_path / "missing"))
    check_version("fake", "queen")
    err = capsys.readouterr().err
    assert "cannot read the" in err and fake_driver.install_hint in err


def test_no_min_version_never_probes(fake_driver, monkeypatch):
    monkeypatch.setattr(fake_driver, "probe", lambda binary: pytest.fail("probed"))
    check_version("fake", "queen")


def test_preflight_warns_on_old_version_once(fake_driver, tmp_path, monkeypatch, capsys):
    from hive import launch
    monkeypatch.setattr(launch, "_warned", set())
    monkeypatch.setattr(fake_driver, "min_version", (9, 0, 0))
    monkeypatch.setattr(fake_driver, "binary", fake_binary(tmp_path))
    pane = SimpleNamespace(name="t-a-1", type="a", index=1, dir="/a", system="fake",
                           command="true", args=[])
    cfg = {"prefix": "t"}
    preflight(cfg, pane)
    preflight(cfg, pane)
    assert capsys.readouterr().err.count("is older than 9.0.0") == 1


def test_warn_untrusted_names_driver(fake_driver, monkeypatch, capsys):
    monkeypatch.setattr(fake_driver, "trust_state", lambda d, c: (d, None, False))
    pane = SimpleNamespace(name="t-a-1", dir="/a", config_dir=None, system="fake")
    warn_untrusted({}, pane)
    assert "fake trust prompt" in capsys.readouterr().err


def test_check_launcher_command_per_driver(fake_driver):
    check_launcher_command("fake-agent", "where", "fake")
    check_launcher_command("claude -n {name} --remote-control {name}", "where", "claude")
    with pytest.raises(ConfigError, match="must contain {name} and --remote-control"):
        check_launcher_command("claude --remote-control", "where", "claude")
