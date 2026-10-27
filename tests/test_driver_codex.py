import json
import os
import subprocess
import tomllib
from types import SimpleNamespace

import pytest

from hive.config import load_config
from hive.drivers import codex as codex_mod
from hive.drivers import common, get_driver
from hive.launch import check_launcher_command, check_version, expand_pane
from hive import sessions
from hive.reconcile import Pane
from hive.tmux import setup_pane
from hive.trust import TrustError
from hive.util import ConfigError

codex = get_driver("codex")

# Screens from Codex 0.164.0 (spike 2026-10-27; hooks review from the R1 planning spike).
TRUST = ("Folder access\n  /x/repo\n  Trust this folder? Codex can read, edit, and run files here,"
         "\n› 1. Trust and continue\n  2. Back to Agent Command Center")
HOOKS_REVIEW = "Hooks need review\n  2 new hooks\n› 1. Review hooks"
LOGIN = ("Welcome to Codex, OpenAI's command-line coding agent\n  Choose how you want to use "
         "Codex.\n> 1. Sign in with ChatGPT\n  2. Sign in with Device Code")
PROMPT = "› Ask Codex to do anything\n  GPT-6.1-Sol default · /x/repo"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(codex_mod, "_daemon_checked", False)


def home():
    return codex_mod.codex_home()


def test_codex_hook_args_empty():
    # Any -c or --dangerously-bypass-hook-trust runs Codex embedded, off the paired daemon.
    assert codex.hook_args(["python3", "/x/hook.py"], "/tmp/st.json") == []


def test_codex_session_and_resume_args():
    assert codex.session_args("abc") == []
    assert codex.resume_args("abc") == ["resume", "abc"]
    assert codex.poll_state({}, "abc") is None


def pane(tmp_path, **kw):
    return Pane(name="cx-t-1", window="cx", type="cx", index=1, dir=str(tmp_path),
                command=codex.default_command, system="codex", **kw)


def test_codex_default_command_places_args_first(tmp_path):
    cfg = {"prefix": "t", "state_dir": str(tmp_path / "state")}
    line = expand_pane(cfg, pane(tmp_path), "abc", resume=True)
    assert line == "codex resume abc -a never -s workspace-write"
    fresh = expand_pane(cfg, pane(tmp_path, args=("--model", "m")), "abc")
    assert fresh == "codex --model m -a never -s workspace-write"  # Codex chooses its own id


def test_codex_no_required_tokens():
    check_launcher_command("sh -c 'exec codex -a never'", "x", "codex")


def git_dir(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_codex_trust_state_non_git_is_trusted(tmp_path):
    assert codex.trust_state(str(tmp_path), None)[2] is True


def test_codex_trust_state_reads_config_toml(tmp_path, monkeypatch):
    git_dir(tmp_path)
    root, path, trusted = codex.trust_state(str(tmp_path), None)
    assert (root, path, trusted) == (tmp_path.resolve(), home() / "config.toml", False)
    home().mkdir()
    (home() / "config.toml").write_text(
        f'[projects."{tmp_path.resolve()}"]\ntrust_level = "trusted"\n')
    assert codex.trust_state(str(tmp_path), None)[2] is True
    other = tmp_path / "cfg"
    assert codex.trust_state(str(tmp_path), str(other)) == (
        tmp_path.resolve(), other / "config.toml", False)


def test_codex_seed_trust_appends_and_verifies(tmp_path):
    home().mkdir()
    path = home() / "config.toml"
    path.write_text('[tui]\nscreen_reader_detection_done = true')  # no trailing newline
    path.chmod(0o600)
    codex.seed_trust(tmp_path, None)
    text = path.read_text()
    assert text.startswith('[tui]\nscreen_reader_detection_done = true\n')
    data = tomllib.loads(text)
    assert data["projects"][str(tmp_path)] == {"trust_level": "trusted"}
    assert data["tui"] == {"screen_reader_detection_done": True}
    assert path.stat().st_mode & 0o777 == 0o600
    codex.seed_trust(tmp_path, None)  # already trusted: unchanged
    assert path.read_text() == text


def test_codex_seed_trust_creates_config_dir(tmp_path, monkeypatch):
    git_dir(tmp_path)
    cfg_dir = tmp_path / "codex-home"
    root, _, trusted = codex.trust_state(str(tmp_path), str(cfg_dir))
    assert not trusted
    codex.seed_trust(root, str(cfg_dir))
    assert codex.trust_state(str(tmp_path), str(cfg_dir))[2] is True


def test_codex_seed_trust_refuses_existing_table(tmp_path):
    home().mkdir()
    path = home() / "config.toml"
    original = f'[projects."{tmp_path}"]\ntrust_level = "untrusted"\n'
    path.write_text(original)
    with pytest.raises(TrustError, match="exists with trust_level = 'untrusted'"):
        codex.seed_trust(tmp_path, None)
    assert path.read_text() == original


def test_codex_seed_trust_refuses_unparseable(tmp_path):
    home().mkdir()
    path = home() / "config.toml"
    path.write_text("not = [valid\n")
    with pytest.raises(TrustError, match="cannot parse"):
        codex.seed_trust(tmp_path, None)
    assert path.read_text() == "not = [valid\n"


def test_codex_seed_trust_restores_when_append_breaks(tmp_path):
    home().mkdir()
    path = home() / "config.toml"
    path.write_text("projects = 1\n")  # an appended [projects."..."] table would not parse
    with pytest.raises(TrustError, match="left unchanged"):
        codex.seed_trust(tmp_path, None)
    assert path.read_text() == "projects = 1\n"


def test_codex_env_rejects_CODEX_HOME(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "xdg" / "hive" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('prefix = "t"\n\n[env]\nCODEX_HOME = "/x"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    with pytest.raises(SystemExit) as exc:
        load_config()
    assert exc.value.code == 2
    assert "hive never sets CODEX_HOME" in capsys.readouterr().err


def write_pid(pid=4242, ticks=99, remote=None):
    d = home() / "app-server-daemon"
    d.mkdir(parents=True)
    (d / "daemon.pid").write_text(json.dumps({"pid": pid, "processIdentity": {"startTicks": ticks}}))
    if remote is not None:
        (d / "settings.json").write_text(json.dumps({"remoteControlEnabled": remote}))


def fake_proc(monkeypatch, alive=True, argv=None):
    monkeypatch.setattr(codex_mod, "_alive", lambda pid, ticks: alive)
    monkeypatch.setattr(codex_mod, "_cmdline", lambda pid: argv)


def record_run(monkeypatch, returncode=0, stderr=""):
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)
    monkeypatch.setattr(codex_mod.subprocess, "run", run)
    return calls


def test_daemon_state():
    assert codex_mod.daemon_state(home()) is None  # no pid file


def test_daemon_state_cmdline_and_settings(monkeypatch):
    write_pid(remote=False)
    fake_proc(monkeypatch, argv=["codex", "app-server", "--remote-control", "--listen", "unix://"])
    assert codex_mod.daemon_state(home()) == "remote"
    fake_proc(monkeypatch, argv=["codex", "app-server", "--listen", "unix://"])
    assert codex_mod.daemon_state(home()) == "plain"
    fake_proc(monkeypatch, argv=None)  # no /proc: settings.json decides
    assert codex_mod.daemon_state(home()) == "plain"
    (home() / "app-server-daemon" / "settings.json").write_text('{"remoteControlEnabled": true}')
    assert codex_mod.daemon_state(home()) == "remote"
    fake_proc(monkeypatch, alive=False)
    assert codex_mod.daemon_state(home()) is None


def test_alive_checks_start_ticks():
    stat = open(f"/proc/{os.getpid()}/stat").read() if os.path.exists("/proc/self/stat") else None
    if stat is None:
        pytest.skip("no /proc")
    ticks = stat.rpartition(")")[2].split()[19]
    assert codex_mod._alive(os.getpid(), int(ticks)) is True
    assert codex_mod._alive(os.getpid(), int(ticks) + 1) is False  # pid reused by another process


def test_ensure_daemon_alive_pid_skips_start(monkeypatch, capsys):
    write_pid()
    fake_proc(monkeypatch, argv=["codex", "app-server", "--remote-control"])
    calls = record_run(monkeypatch)
    codex_mod.ensure_daemon({})
    assert calls == [] and capsys.readouterr().err == ""


def test_ensure_daemon_plain_warns_never_starts(monkeypatch, capsys):
    write_pid()
    fake_proc(monkeypatch, argv=["codex", "app-server"])
    calls = record_run(monkeypatch)
    codex_mod.ensure_daemon({})
    assert calls == []
    assert "runs without remote control" in capsys.readouterr().err


def test_ensure_daemon_starts_when_absent(monkeypatch, capsys):
    monkeypatch.setenv("CODEX_HOME", "/elsewhere")
    calls = record_run(monkeypatch)
    codex_mod.ensure_daemon({"FOO": "1"})
    codex_mod.ensure_daemon({"FOO": "1"})  # once per process
    ((cmd, kw),) = calls
    assert cmd == ["codex", "remote-control", "start"]
    assert kw["env"]["FOO"] == "1" and "CODEX_HOME" not in kw["env"] and kw["timeout"]
    assert capsys.readouterr().err == ""


def test_ensure_daemon_start_failure_warns(monkeypatch, capsys):
    record_run(monkeypatch, returncode=1, stderr="boom\nnot paired\n")
    codex_mod.ensure_daemon({})
    assert "'codex remote-control start' failed: not paired" in capsys.readouterr().err


def test_prepare_launch_default_home_ensures_daemon(tmp_path, monkeypatch):
    calls = record_run(monkeypatch)
    assert codex.prepare_launch({}, pane(tmp_path)) is None
    assert [c[0] for c in calls] == [["codex", "remote-control", "start"]]


def test_prepare_launch_with_config_dir_skips_daemon(tmp_path, monkeypatch):
    calls = record_run(monkeypatch)
    assert codex.prepare_launch({}, pane(tmp_path, config_dir=str(tmp_path / "h"))) is None
    assert calls == []


def test_waiting_kind_codex_trust():
    assert codex.waiting_kind(TRUST) == "trust"


def test_waiting_kind_codex_hooks_review():
    assert codex.waiting_kind(HOOKS_REVIEW) == "hooks_review"


def test_waiting_kind_codex_login():
    assert codex.waiting_kind(LOGIN) == "login"


def test_waiting_kind_codex_none():
    assert codex.waiting_kind(PROMPT) is None


def test_codex_probe(tmp_path, monkeypatch):
    def run(cmd, **kw):
        return SimpleNamespace(stdout=version, stderr="", returncode=0)
    monkeypatch.setattr(common.subprocess, "run", run)
    version = "codex-cli 0.164.0\n"
    assert codex.probe("codex") == "0.164.0"
    check_version("codex", "cx")
    version = "codex-cli 0.150.0\n"
    with pytest.raises(ConfigError) as exc:
        check_version("codex", "cx")
    assert "0.150.0 is older than 0.164.0" in str(exc.value)
    assert "npm install -g @openai/codex" in str(exc.value)


def test_setup_pane_resume_still_ensures_daemon(tmp_path, monkeypatch):
    calls = record_run(monkeypatch)
    typed = []

    def fake_tmux(cfg, *args, check=True):
        if args[0] == "send-keys" and "-l" in args:
            typed.append(args[-1])
        return SimpleNamespace(returncode=0, stdout="%1\n", stderr="")
    monkeypatch.setattr("hive.tmux.tmux", fake_tmux)
    monkeypatch.setattr(sessions, "pending_resume", lambda cfg, name: "abc")
    monkeypatch.setattr(sessions, "forget", lambda cfg, names: None)
    cfg = {"prefix": "t", "state_dir": str(tmp_path / "state"), "env": {}, "pane_shell": None}
    assert setup_pane(cfg, pane(tmp_path), "%1") == "abc"
    assert [c[0] for c in calls] == [["codex", "remote-control", "start"]]
    assert "codex resume abc -a never -s workspace-write" in typed[0]


def test_stop_keep_session_refused_for_codex(tmp_path, monkeypatch, capsys):
    import sys
    from hive import cli
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setattr("hive.lock._lock", None)
    monkeypatch.setattr("hive.config._profile_option", None)
    monkeypatch.setattr("hive.workers.reconcile_if_up", lambda cfg: 0)
    path = xdg / "hive" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(f'prefix = "t"\ntmux_socket = "hive-test-cx-{os.getpid()}"\n\n[[agents]]\n'
                    f'type = "cx"\ndir = "{tmp_path}"\nsystem = "codex"\ncount = 1\n')
    before = path.read_text()
    monkeypatch.setattr(sys, "argv", ["hive", "stop", "cx-t-1", "--keep-session"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "codex: session capture not supported in this release" in err
    assert "`codex resume` inside a new pane" in err
    assert path.read_text() == before


def test_codex_trust_state_dot_codex_dir_needs_trust(tmp_path, monkeypatch):
    """Codex asks to trust a non-git dir once it has its own .codex/ (the queen dir)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "q" / ".codex").mkdir(parents=True)
    root, path, trusted = codex.trust_state(str(tmp_path / "q"), None)
    assert (root, trusted) == (tmp_path / "q", False)
    codex.seed_trust(root, None)
    assert codex.trust_state(str(tmp_path / "q"), None)[2] is True


@pytest.mark.parametrize("command, args, want", [
    ("codex {args} -a never -s workspace-write", (), "codex {args} -a never -s danger-full-access"),
    ("codex --sandbox=read-only", (), "codex -s danger-full-access -a never"),
    ("codex", (), "codex -s danger-full-access -a never"),
    ("codex {args}", ("-s", "read-only", "-a", "on-request"), "codex {args}"),
])
def test_codex_queen_extras(command, args, want):
    got = codex.queen_extras(command, args)
    assert got == want
    assert "-c" not in got.split() and "workspace-write" not in got
    assert codex.queen_extras(got, args) == got  # idempotent


def test_codex_queen_config_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "hive").mkdir()
    (tmp_path / "hive" / "config.toml").write_text('[queen]\nsystem = "codex"\n')
    cfg = load_config()
    assert cfg["queen"]["system"] == "codex"
    assert cfg["queen"]["command"] == "codex {args} -a never -s danger-full-access"
