"""CLI robustness: config errors, lenient down/status, locking, service unit, warnings.

Runs main() with HOME and XDG_CONFIG_HOME under tmp_path. tmux is never the real one:
tests either stub hive.tmux.tmux or put a fake `tmux` first on PATH.
"""

import json
import os
import stat
import sys
import tomllib
from importlib import resources
from types import SimpleNamespace

import pytest

from hive import cli, lock
from hive.config import edit_config, load_config, parse_config
from hive.drivers.claude import QUEEN_TOOLS
from hive.launch import preflight, queen_command_line, warn_untrusted
from hive.lifecycle import cmd_up, reconcile
from hive.queen import materialize_queen
from hive.reconcile import RunningPane
from hive.service import service_exe, unit_quote

SOCKET = f"hive-test-cli-{os.getpid()}"
BASE = f'prefix = "t"\ntmux_socket = "{SOCKET}"\n\n[defaults]\ncommand = "sleep 600 {{name}} --remote-control"\n'


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr("hive.lock._lock", None)
    monkeypatch.setattr("hive.launch._warned", set())
    monkeypatch.setattr("hive.config._profile_option", None)  # restored after run() sets it
    cfg = xdg / "hive" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(BASE)
    return SimpleNamespace(tmp=tmp_path, home=home, xdg=xdg, cfg=cfg)


def hive(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["hive", *argv])
    try:
        code = cli.main()
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    assert "Traceback" not in out.err
    return code, out.out, out.err


def fake_bin(tmp_path, monkeypatch, name, body="exit 0"):
    """A fake executable that logs its arguments to <name>.log; PATH is only that dir."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    script = d / name
    log = d / f"{name}.log"
    script.write_text(f'#!/bin/sh\necho "$@" >> {log}\n{body}\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}/usr/bin{os.pathsep}/bin")
    return log


# --- config validation (R1, R6, R15, U6) -------------------------------------

@pytest.mark.parametrize("line,key", [
    ('prefix = "a.b"', "prefix"), ('prefix = "a:b"', "prefix"), ('prefix = "a b"', "prefix"),
    ('prefix = ""', "prefix"), ('session = "x.y"', "session"), ('session = "x y"', "session"),
])
def test_names_with_dot_colon_space_are_rejected(env, monkeypatch, capsys, line, key):
    env.cfg.write_text(line + "\n" + BASE.split("\n", 1)[1].replace(f'tmux_socket = "{SOCKET}"\n', "")
                       if key != "tmux_socket" else line + '\nprefix = "t"\n[defaults]\ncommand = "c"\n')
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 2 and err.startswith("hive: error: ") and f"'{key}'" in err


@pytest.mark.parametrize("kind", ["a b", "a:b", "a/b"])
def test_agent_type_is_checked_like_spawn(env, monkeypatch, capsys, kind):
    env.cfg.write_text(BASE + f'\n[[agents]]\ntype = "{kind}"\ndir = "/tmp"\n')
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 2 and "agents[1].type" in err and kind in err


@pytest.mark.parametrize("snippet,text", [
    ('search_roots = ["rel"]\n', "search_roots entry 'rel' must be an absolute path"),
    ('search_roots = [""]\n', "search_roots entry must not be empty"),
    ('search_roots = ["~nosuchuser_hive/x"]\n', "unknown user"),
])
def test_bad_search_roots(env, monkeypatch, capsys, snippet, text):
    env.cfg.write_text(snippet + BASE)
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 2 and text in err


@pytest.mark.parametrize("dir_,text", [("rel", "agents[1].dir 'rel' must be an absolute path"),
                                       ("", "agents[1].dir must not be empty")])
def test_bad_agent_dir(env, monkeypatch, capsys, dir_, text):
    env.cfg.write_text(BASE + f'\n[[agents]]\ntype = "a"\ndir = "{dir_}"\n')
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 2 and text in err


@pytest.mark.parametrize("extra", ['[defaults]\ncommand = "  "\n', 'shell = ""\n'])
def test_empty_command_and_shell_are_rejected(env, monkeypatch, capsys, extra):
    env.cfg.write_text(extra if extra.startswith("[") else extra + BASE)
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 2 and "must not be empty" in err


def test_toml_type_messages(env, monkeypatch, capsys):
    env.cfg.write_text("agents = 3\n" + BASE)
    assert "'agents' must be an array of [[agents]] tables" in hive(monkeypatch, capsys, "list")[2]
    env.cfg.write_text(BASE + '\n[[agents]]\ntype = "a"\ndir = "/tmp"\ncount = "x"\n')
    assert "'agents[1].count' must be an integer" in hive(monkeypatch, capsys, "list")[2]
    env.cfg.write_text('login_shell = 1\n' + BASE)
    assert "'login_shell' must be true or false" in hive(monkeypatch, capsys, "list")[2]


# --- R3: unreadable config ---------------------------------------------------

def test_config_is_a_directory(env, monkeypatch, capsys):
    env.cfg.unlink()
    env.cfg.mkdir()
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 2 and f"cannot read {env.cfg}" in err


def test_config_not_utf8(env, monkeypatch, capsys):
    env.cfg.write_bytes(b'prefix = "\xff\xfe"\n')
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 2 and f"cannot read {env.cfg}" in err


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
def test_config_unreadable(env, monkeypatch, capsys):
    env.cfg.chmod(0)
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 2 and f"cannot read {env.cfg}" in err


# --- R2: down and status survive a broken config ------------------------------

def test_down_with_broken_config_uses_the_parsable_socket(env, monkeypatch, capsys):
    log = fake_bin(env.tmp, monkeypatch, "tmux", "exit 1")
    env.cfg.write_text(BASE + "\nbogus = 1\n")
    code, out, err = hive(monkeypatch, capsys, "down")
    assert code == 0 and "not running" in out
    assert "hive: warning: config problem" in err and "unknown key 'bogus'" in err
    assert f"-L {SOCKET} has-session -t =t-agents" in log.read_text()


def test_down_with_unparsable_config_falls_back_to_defaults(env, monkeypatch, capsys):
    log = fake_bin(env.tmp, monkeypatch, "tmux", "exit 1")
    env.cfg.write_text("this is [not toml\n")
    code, out, err = hive(monkeypatch, capsys, "down")
    assert code == 0 and "hive: warning: config problem" in err
    assert "-L hive has-session" in log.read_text()
    code, out, err = hive(monkeypatch, capsys, "status")
    assert code == 1 and out == "not running\n" and "config problem" in err


def test_down_with_unparsable_config_keeps_its_own_socket(env, monkeypatch, capsys):
    # A typo after tmux_socket must not send `down` to the default `hive` socket.
    log = fake_bin(env.tmp, monkeypatch, "tmux", "exit 1")
    env.cfg.write_text(f'tmux_socket = "{SOCKET}"\nbogus = [\n')
    code, _, err = hive(monkeypatch, capsys, "down")
    assert code == 0 and f"on socket {SOCKET}" in err
    assert f"-L {SOCKET} has-session" in log.read_text()
    assert "-L hive " not in log.read_text()


def test_dotted_socket_name_is_valid(env, monkeypatch, capsys):
    env.cfg.write_text(BASE.replace(f'tmux_socket = "{SOCKET}"', 'tmux_socket = "x.y"'))
    code, _, err = hive(monkeypatch, capsys, "list")
    assert "tmux_socket" not in err
    assert parse_config()["socket"] == "x.y"


@pytest.mark.parametrize("bad", ['prefix = "a.b"', 'session = "x:y"', "prefix = 3",
                                 "tmux_socket = 'mysock", 'tmux_socket = "a b"', 'tmux_socket = ""'])
def test_down_with_a_set_but_invalid_name_dies(env, monkeypatch, capsys, bad):
    log = fake_bin(env.tmp, monkeypatch, "tmux", "exit 1")
    socket_line = "" if bad.startswith("tmux_socket") else f'tmux_socket = "{SOCKET}"\n'
    env.cfg.write_text(f'{bad}\n{socket_line}prefix2 = [\n')
    code, _, err = hive(monkeypatch, capsys, "down")
    assert code == 2
    assert not log.exists() or "-L hive" not in log.read_text()


def test_down_without_a_config_still_errors(env, monkeypatch, capsys):
    env.cfg.unlink()
    code, _, err = hive(monkeypatch, capsys, "down")
    assert code == 2 and "not found" in err


def test_other_commands_die_on_a_broken_config(env, monkeypatch, capsys):
    env.cfg.write_text(BASE + "\nbogus = 1\n")
    for cmd in ("list", "up", "reconcile"):
        assert hive(monkeypatch, capsys, cmd)[0] == 2


# --- R9: lock after config; lock errors --------------------------------------

def test_no_config_means_no_lock_file(env, monkeypatch, capsys):
    env.cfg.unlink()
    code, _, err = hive(monkeypatch, capsys, "up")
    assert code == 2 and "not found" in err
    assert not (env.xdg / "hive" / ".lock").exists()


def test_lock_dir_not_creatable(env, monkeypatch, capsys):
    blocker = env.tmp / "file"
    blocker.write_text("")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(blocker))
    with pytest.raises(SystemExit) as exc:
        lock.hold_lock()
    assert exc.value.code == 1
    assert "cannot open lock" in capsys.readouterr().err


def test_down_continues_without_lock(env, monkeypatch, capsys):
    blocker = env.tmp / "file"
    blocker.write_text("")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(blocker))
    lock.hold_lock(required=False)  # warns, does not exit
    assert lock._lock is None
    assert "continuing without it" in capsys.readouterr().err


# --- R10 ---------------------------------------------------------------------

def test_ctrl_c_and_broken_pipe(monkeypatch, capsys):
    def interrupt():
        raise KeyboardInterrupt
    monkeypatch.setattr("hive.cli.run", interrupt)
    assert cli.main() == 130
    assert capsys.readouterr().err == "hive: interrupted\n"

    def pipe():
        raise BrokenPipeError
    monkeypatch.setattr("hive.cli.run", pipe)
    monkeypatch.setattr(os, "dup2", lambda *a: None)
    assert cli.main() == 1
    assert capsys.readouterr().err == ""


# --- R4, R5 ------------------------------------------------------------------

@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
def test_spawn_in_a_read_only_config_dir_seeds_no_trust(env, monkeypatch, capsys):
    proj = env.tmp / "proj"
    proj.mkdir()
    (env.xdg / "hive" / ".lock").write_text("")
    (env.xdg / "hive").chmod(0o555)
    try:
        code, _, err = hive(monkeypatch, capsys, "spawn", str(proj), "--trust")
    finally:
        (env.xdg / "hive").chmod(0o755)
    assert code == 1 and f"cannot write {env.cfg}" in err
    assert not (env.home / ".claude.json").exists()


def test_edit_config_reports_read_and_write_errors(env, monkeypatch, capsys):
    cfg = {"config_path": str(env.tmp / "missing.toml")}
    with pytest.raises(SystemExit) as exc:
        edit_config(cfg, lambda t: t, lambda d: None)
    assert exc.value.code == 1 and "cannot read" in capsys.readouterr().err

    def deny(path, text):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr("hive.config.write_atomic", deny)
    with pytest.raises(SystemExit) as exc:
        edit_config({"config_path": str(env.cfg)}, lambda t: t, lambda d: None)
    assert exc.value.code == 1 and f"cannot write {env.cfg}" in capsys.readouterr().err


def test_unknown_user_in_cli_args(env, monkeypatch, capsys):
    code, _, err = hive(monkeypatch, capsys, "roots", "add", "~nosuchuser_hive/x")
    assert code == 2 and "unknown user" in err
    code, _, err = hive(monkeypatch, capsys, "spawn", "~nosuchuser_hive/x")
    assert code == 2 and "unknown user" in err


# --- R7 ----------------------------------------------------------------------

class FakeTmux:
    def __init__(self):
        self.calls = []

    def __call__(self, cfg, *args, check=True):
        self.calls.append(args)
        rc = 1 if args[0] == "has-session" else 0
        return SimpleNamespace(returncode=rc, stdout="%1\n", stderr="")


@pytest.mark.parametrize("exc", [SystemExit(1), KeyboardInterrupt(), RuntimeError("boom")])
def test_up_removes_the_half_built_session_on_any_failure(env, monkeypatch, capsys, exc):
    fake = FakeTmux()
    monkeypatch.setattr("hive.tmux.tmux", fake)

    def failing(cfg, **kw):
        raise exc
    monkeypatch.setattr("hive.lifecycle.reconcile", failing)
    cfg = load_config()
    with pytest.raises(type(exc)):
        cmd_up(cfg, None)
    assert ("kill-session", "-t", "=t-agents") in fake.calls
    assert "removed session t-agents" in capsys.readouterr().err


def test_materialize_queen_dies_on_oserror(env, capsys):
    cfg = load_config()
    qdir = env.xdg / "hive" / "queen"
    qdir.write_text("a file, not a dir")
    with pytest.raises(SystemExit) as exc:
        materialize_queen(cfg)
    assert exc.value.code == 1 and "cannot write the queen dir" in capsys.readouterr().err


# --- R8 ----------------------------------------------------------------------

def test_discover_times_out(env, monkeypatch, capsys):
    monkeypatch.setattr("hive.launchers.DISCOVER_TIMEOUT", 0.3)
    env.cfg.write_text(BASE + '\n[queen]\ndiscover = "sleep 5"\n')
    code, _, err = hive(monkeypatch, capsys, "spawn", "x", "--sandbox", "n")
    assert code == 1 and "discover command timed out" in err


def test_sandbox_discover_runs_before_the_lock(env, monkeypatch, capsys):
    order = []
    monkeypatch.setattr("hive.launchers.launcher_record", lambda cfg, name: order.append("discover"))
    monkeypatch.setattr("hive.lock.hold_lock", lambda **_: order.append("lock"))
    monkeypatch.setattr("hive.workers.cmd_spawn", lambda cfg, args: 0)
    env.cfg.write_text(BASE + '\n[queen]\ndiscover = "true"\n')
    assert hive(monkeypatch, capsys, "spawn", "x", "--sandbox", "n")[0] == 0
    assert order == ["discover", "lock"]


# --- R12 ---------------------------------------------------------------------

def test_status_survives_a_tab_in_the_pane_title(env, monkeypatch, capsys):
    class Tmux(FakeTmux):
        def __call__(self, cfg, *args, check=True):
            if args[0] == "list-panes":
                return SimpleNamespace(returncode=0, stderr="",
                                       stdout="0\twin\t0\tsleep\ta\ttitle\twith\ttabs\n")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr("hive.tmux.tmux", Tmux())
    code, out, _ = hive(monkeypatch, capsys, "status")
    assert code == 0 and "pane 0: a\ttitle\twith\ttabs  (sleep)" in out


# --- R11, U9: the service unit -----------------------------------------------

def test_service_commands_refuse_on_macos(env, monkeypatch, capsys):
    log = fake_bin(env.tmp, monkeypatch, "systemctl")
    monkeypatch.setattr(sys, "platform", "darwin")
    for cmd in ("install-service", "uninstall-service"):
        code, _, err = hive(monkeypatch, capsys, cmd)
        assert code == 1 and f"{cmd} is Linux-only (systemd)" in err
        assert "Run at login on macOS" in err
    assert not (env.home / ".config" / "systemd").exists()
    assert not (env.xdg / "systemd").exists()
    assert not log.exists()


def test_materialized_guard_hook_uses_hives_interpreter(env):
    cfg = {"queen": {"dir": str(env.tmp / "queen")}}
    materialize_queen(cfg)
    path = env.tmp / "queen" / ".claude" / "settings.json"
    got = json.loads(path.read_text())
    want = json.loads(resources.files("hive").joinpath("queen", "settings.json").read_text())
    hook = got["hooks"]["PreToolUse"][0]["hooks"][0]
    assert hook["command"] == sys.executable
    hook["command"] = "python3"
    assert got == want
    before = path.stat().st_mtime_ns
    materialize_queen(cfg)  # unchanged bytes are not rewritten
    assert path.stat().st_mtime_ns == before


def test_install_service_without_systemctl_writes_nothing(env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(env.tmp / "empty"))
    code, _, err = hive(monkeypatch, capsys, "install-service")
    assert code == 1 and "systemctl not found" in err
    assert not (env.home / ".config" / "systemd").exists()
    assert not (env.xdg / "systemd").exists()


def test_install_service_path_env_and_next_steps(env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    log = fake_bin(env.tmp, monkeypatch, "systemctl")
    code, out, _ = hive(monkeypatch, capsys, "install-service")
    unit = env.home / ".config" / "systemd" / "user" / "hive.service"
    assert code == 0 and unit.exists() and not (env.xdg / "systemd").exists()
    text = unit.read_text()
    assert f"Environment=XDG_CONFIG_HOME={env.xdg}\n" in text
    assert "systemctl --user enable --now hive.service" in out
    assert "loginctl enable-linger $USER" in out
    assert "--user daemon-reload" in log.read_text()
    # the same unit path is used to uninstall; a second time it is a no-op
    assert hive(monkeypatch, capsys, "uninstall-service")[0] == 0
    assert not unit.exists()
    code, out, _ = hive(monkeypatch, capsys, "uninstall-service")
    assert code == 0 and "not installed" in out


def test_install_service_default_xdg_adds_no_environment_and_enable_skips_hint(
        env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    fake_bin(env.tmp, monkeypatch, "systemctl")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(env.home / ".config"))
    cfg = env.home / ".config" / "hive" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(BASE)
    code, out, _ = hive(monkeypatch, capsys, "install-service", "--enable")
    unit = env.home / ".config" / "systemd" / "user" / "hive.service"
    assert code == 0 and "XDG_CONFIG_HOME" not in unit.read_text() and "next:" not in out


def test_unit_exe_is_escaped_for_systemd(monkeypatch):
    monkeypatch.setattr("hive.service.shutil.which", lambda name: "/opt/my tools/100%/hive")
    assert service_exe() == '"/opt/my tools/100%%/hive"'
    assert unit_quote("/usr/bin/hive") == "/usr/bin/hive"
    assert unit_quote("a$b") == "a$$b"


# --- U1, R15: warnings when panes start ---------------------------------------

def pane(command):
    return SimpleNamespace(name="t-a-1", type="a", index=1, dir="/tmp", command=command, args=(),
                           system="claude")


def test_preflight_warns_about_missing_program_and_remote_control(env, monkeypatch, capsys):
    cfg = load_config()
    preflight(cfg, pane("nosuchprogram-hive FOO {name}"))
    err = capsys.readouterr().err
    assert "hive: warning: t-a-1: command has no --remote-control" in err
    assert "'nosuchprogram-hive' not found in PATH" in err
    preflight(cfg, pane("FOO=1 sh {name} --remote-control"))
    assert capsys.readouterr().err == ""


def test_preflight_is_not_run_by_list(env, monkeypatch, capsys):
    env.cfg.write_text(BASE.replace("--remote-control", "") + '\n[[agents]]\ntype = "a"\ndir = "/tmp"\n')
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 0 and "warning" not in err


# --- U3, U4: reconcile summary and untrusted warning ---------------------------

def test_reconcile_summarizes_skipped_agents(env, monkeypatch, capsys):
    fake = FakeTmux()
    monkeypatch.setattr("hive.tmux.tmux", fake)
    monkeypatch.setattr("hive.tmux.running_panes", lambda cfg: ({}, []))
    monkeypatch.setattr("hive.tmux.session_running", lambda cfg: True)
    monkeypatch.setattr("hive.lifecycle.warn_untrusted", lambda cfg, p: None)
    monkeypatch.setattr("hive.tmux.start_pane", lambda *a: "%2")
    monkeypatch.setattr("hive.tmux.window_ids", lambda cfg: {})
    monkeypatch.setattr("hive.lifecycle.materialize_queen", lambda cfg: None)
    env.cfg.write_text(BASE + f'\n[[agents]]\ntype = "gone"\ndir = "{env.tmp / "gone"}"\ncount = 2\n')
    assert reconcile(load_config()) == 0
    err = capsys.readouterr().err
    assert "hive: warning: 1 agent(s) skipped: dir missing; see 'hive list'" in err


def test_untrusted_warning_has_prefix_and_remedy(env, capsys):
    cfg = load_config()
    warn_untrusted(cfg, pane("x").__class__(name="t-queen", type="queen", index=1,
                                            dir=str(env.tmp), command="x", config_dir=None,
                                            system="claude"))
    err = capsys.readouterr().err
    assert err.startswith(f"hive: warning: untrusted t-queen {env.tmp}")
    assert "trust prompt" in err and "--trust" in err


# --- U2, U5, U7, U8, R23 ---------------------------------------------------------

def test_init_prints_session_and_socket(env, monkeypatch, capsys):
    env.cfg.unlink()
    code, out, _ = hive(monkeypatch, capsys, "init")
    assert code == 0 and "session=" in out and "socket=hive" in out and "tmux_socket" in out


def test_stop_unknown_type_has_its_own_message(env, monkeypatch, capsys):
    code, _, err = hive(monkeypatch, capsys, "stop", "nope")
    assert code == 2 and "no agent type 'nope'; 'hive list' shows the types" in err
    assert "search_roots" not in err


def test_spawn_invalid_type_suggests_a_type(env, monkeypatch, capsys):
    proj = env.tmp / "my proj:x"
    proj.mkdir()
    code, _, err = hive(monkeypatch, capsys, "spawn", str(proj))
    assert code == 2 and "--type my-proj-x" in err


def test_help_texts(monkeypatch, capsys):
    out = hive(monkeypatch, capsys, "--help")[1]
    assert "exit codes:" in out


def test_queen_flags_are_added_once():
    base = "claude -n {name} --remote-control {name}"
    line = queen_command_line(base)
    assert line == f"{base} --tools {QUEEN_TOOLS} --strict-mcp-config"
    assert queen_command_line(line) == line
    own = queen_command_line("c --tools Read --strict-mcp-config")
    assert own == "c --tools Read --strict-mcp-config"
    assert queen_command_line("c --tools=Read").count("--tools") == 1


def test_queen_tools_match_guard():
    """The queen's --tools list and the guard's allowlist must name the same tools."""
    import importlib.util
    from pathlib import Path
    path = Path(cli.__file__).parent / "queen" / "hooks" / "guard.py"
    spec = importlib.util.spec_from_file_location("hive_guard", path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    assert set(QUEEN_TOOLS.split(",")) == guard.QUEEN_TOOLS



# --- R0: named profiles and a disabled queen ---------------------------------------

def profile_cfg(env, name, text):
    path = env.xdg / "hive" / "profiles" / name / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_lenient_down_refuses_collision(env, monkeypatch, capsys):
    fake = FakeTmux()
    monkeypatch.setattr("hive.tmux.tmux", fake)
    profile_cfg(env, "t", 'tmux_socket = "hive"\nbogus = [\n')
    code, _, err = hive(monkeypatch, capsys, "--profile", "t", "down")
    assert code == 2 and "is the default profile's socket" in err
    # the default profile's own socket is refused too
    profile_cfg(env, "t", f'tmux_socket = "{SOCKET}"\nbogus = [\n')
    code, _, err = hive(monkeypatch, capsys, "--profile", "t", "status")
    assert code == 2 and "is the default profile's socket" in err
    assert fake.calls == []


def test_profile_unit_name(env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    log = fake_bin(env.tmp, monkeypatch, "systemctl")
    profile_cfg(env, "t", BASE.replace(SOCKET, SOCKET + "-t"))
    code, out, _ = hive(monkeypatch, capsys, "--profile", "t", "install-service")
    units = env.home / ".config" / "systemd" / "user"
    assert code == 0 and [p.name for p in units.iterdir()] == ["hive-t.service"]
    text = (units / "hive-t.service").read_text()
    assert "ExecStart=%h/.local/bin/hive --profile t up\n" in text
    assert "ExecStop=%h/.local/bin/hive --profile t down\n" in text
    assert "enable --now hive-t.service" in out
    assert hive(monkeypatch, capsys, "--profile", "t", "uninstall-service")[0] == 0
    assert "disable --now hive-t.service" in log.read_text()
    assert "hive.service" not in log.read_text()


def test_restart_named_profile_never_checks_hive_service(env, monkeypatch, capsys):
    log = fake_bin(env.tmp, monkeypatch, "systemctl", "exit 1")  # unit not active
    monkeypatch.setattr("hive.tmux.tmux", FakeTmux())
    profile_cfg(env, "t", BASE.replace(SOCKET, SOCKET + "-t") + '\n[queen]\nenabled = false\n')
    code, out, _ = hive(monkeypatch, capsys, "--profile", "t", "restart")
    assert code == 0 and "nothing to start" in out
    assert log.read_text() == "--user is-active --quiet hive-t.service\n"


def test_install_service_named_profile_on_macos(env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "darwin")
    profile_cfg(env, "t", BASE.replace(SOCKET, SOCKET + "-t"))
    code, _, err = hive(monkeypatch, capsys, "--profile", "t", "install-service")
    assert code == 1 and "install-service is Linux-only (systemd)" in err
    assert not (env.home / ".config" / "systemd").exists()


DISABLED = BASE + '\n[queen]\nenabled = false\n'


def test_up_empty_hive(env, monkeypatch, capsys):
    fake = FakeTmux()
    monkeypatch.setattr("hive.tmux.tmux", fake)
    monkeypatch.setattr("hive.tmux.session_running", lambda cfg: False)
    env.cfg.write_text(DISABLED)
    code, out, _ = hive(monkeypatch, capsys, "up")
    assert code == 0 and out == "nothing to start: queen disabled and no agents\n"
    assert fake.calls == []
    assert not (env.xdg / "hive" / "queen").exists()


def test_up_first_pane_is_worker(env, monkeypatch, capsys):
    fake = FakeTmux()
    monkeypatch.setattr("hive.tmux.tmux", fake)
    monkeypatch.setattr("hive.lifecycle.reconcile", lambda cfg, **kw: 0)
    (env.tmp / "w").mkdir()
    env.cfg.write_text(DISABLED + f'\n[[agents]]\ntype = "w"\ndir = "{env.tmp / "w"}"\n')
    code, out, _ = hive(monkeypatch, capsys, "up")
    new = next(c for c in fake.calls if c[0] == "new-session")
    assert code == 0 and new[new.index("-n") + 1] == "w-t" and new[new.index("-c") + 1] == str(env.tmp / "w")
    assert "started w-t-1" in out and not (env.xdg / "hive" / "queen").exists()


def test_list_queen_disabled(env, monkeypatch, capsys):
    monkeypatch.setattr("hive.tmux.session_running", lambda cfg: True)
    monkeypatch.setattr("hive.tmux.tmux", FakeTmux())
    queen = RunningPane("%0", "@0", "hive-queen-t", "hive-queen-t", "queen", 1, False)
    monkeypatch.setattr("hive.tmux.running_panes", lambda cfg: ({"hive-queen-t": queen}, []))
    env.cfg.write_text(DISABLED)
    code, out, _ = hive(monkeypatch, capsys, "list")
    lines = out.splitlines()
    assert code == 0 and lines[1].startswith("queen name=hive-queen-t running=yes")
    assert lines[1].endswith(" enabled=no system=claude")
    assert "drift start=none stop=hive-queen-t" in lines


# --- per-instance removal (R2, D6) ---------------------------------------------

def agents_cfg(env, *blocks):
    (env.tmp / "a").mkdir(exist_ok=True)
    text = BASE + "".join(f'\n[[agents]]\ntype = "{t}"\ndir = "{env.tmp / "a"}"\n{extra}\n'
                          for t, extra in blocks)
    env.cfg.write_text(text)


def agent_entry(env, kind):
    return next(a for a in tomllib.loads(env.cfg.read_text())["agents"] if a["type"] == kind)


def test_parse_indices_and_count_exclusive(env, monkeypatch, capsys):
    agents_cfg(env, ("a", "count = 2\nindices = [2]"))
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 2 and "agents[1] has both 'count' and 'indices'" in err


@pytest.mark.parametrize("value", ["[0]", "[2, 2]", "[true]", '["2"]', "2"])
def test_parse_indices_invalid(env, monkeypatch, capsys, value):
    agents_cfg(env, ("a", f"indices = {value}"))
    code, _, err = hive(monkeypatch, capsys, "list")
    assert code == 2 and "agents[1].indices" in err


@pytest.mark.parametrize("argv", [["a", "--index", "1"], ["a-t-1"]])
def test_stop_one_instance(env, monkeypatch, capsys, argv):
    agents_cfg(env, ("a", "count = 2"))
    code, out, err = hive(monkeypatch, capsys, "stop", *argv)
    assert code == 0, err
    assert f"config agent=a count=2->1 indices=2 file={env.cfg}" in out
    assert agent_entry(env, "a") == {"type": "a", "dir": str(env.tmp / "a"), "indices": [2]}


def test_stop_several_instance_names(env, monkeypatch, capsys):
    agents_cfg(env, ("a", "count = 3"), ("b", "count = 2"))
    code, out, err = hive(monkeypatch, capsys, "stop", "a-t-1", "a-t-3", "b-t-2")
    assert code == 0, err
    assert agent_entry(env, "a")["indices"] == [2] and agent_entry(env, "b")["count"] == 1
    assert "config agent=a count=3->1 indices=2" in out and "config agent=b count=2->1 " in out


def test_stop_n_with_sparse_takes_highest(env, monkeypatch, capsys):
    agents_cfg(env, ("a", "indices = [2, 4, 5]"))
    code, _, err = hive(monkeypatch, capsys, "stop", "a", "-n", "2")
    assert code == 0, err
    assert agent_entry(env, "a")["indices"] == [2]


def test_stop_type_wins_over_instance_name(env, monkeypatch, capsys):
    agents_cfg(env, ("a", "count = 1"), ("a-t-1", "count = 2"))
    code, _, err = hive(monkeypatch, capsys, "stop", "a-t-1")
    assert code == 0
    assert agent_entry(env, "a-t-1")["count"] == 1 and agent_entry(env, "a")["count"] == 1
    assert "hive stop a --index 1" in err


@pytest.mark.parametrize("argv,text", [
    (["a", "a-t-1"], "'a' is a type"),
    (["a-t-1", "-n", "1"], "-n and --index take one TYPE target"),
    (["a", "-n", "1", "--index", "1"], "give -n or --index, not both"),
    (["a", "--index", "3"], "type 'a' has no instance 3 (instances: 1,2)"),
])
def test_stop_usage_errors(env, monkeypatch, capsys, argv, text):
    agents_cfg(env, ("a", "count = 2"))
    before = env.cfg.read_text()
    code, _, err = hive(monkeypatch, capsys, "stop", *argv)
    assert code == 2 and text in err and env.cfg.read_text() == before


@pytest.mark.parametrize("name", ["a-t-3", "zz-t-1", "a-other-1"])
def test_stop_unknown_name(env, monkeypatch, capsys, name):
    agents_cfg(env, ("a", "count = 2"))
    code, _, err = hive(monkeypatch, capsys, "stop", name)
    if name == "a-other-1":  # not an instance name for prefix t: an unknown type
        assert code == 2 and "no agent type 'a-other-1'" in err
    else:
        assert code == 2 and f"no instance '{name}'" in err and "--index" in err


def test_stop_queen_instance_name(env, monkeypatch, capsys):
    agents_cfg(env, ("a", "count = 1"))
    code, _, err = hive(monkeypatch, capsys, "stop", "hive-queen-t")
    assert code == 2 and "the queen is always running" in err


def test_spawn_fills_lowest_free(env, monkeypatch, capsys):
    (env.home / ".claude.json").write_text(json.dumps(
        {"projects": {str(env.tmp / "a"): {"hasTrustDialogAccepted": True}}}))
    agents_cfg(env, ("a", "indices = [2, 4]"))
    code, out, err = hive(monkeypatch, capsys, "spawn", "a")
    assert code == 0, err
    assert agent_entry(env, "a")["indices"] == [1, 2, 4] and "count=2->3 indices=1,2,4" in out
    code, out, err = hive(monkeypatch, capsys, "spawn", "a")
    assert code == 0, err
    assert agent_entry(env, "a")["count"] == 4 and "indices" not in agent_entry(env, "a")


def test_list_shows_indices_when_sparse(env, monkeypatch, capsys):
    agents_cfg(env, ("a", "indices = [2, 3]"), ("b", "count = 2"))
    code, out, _ = hive(monkeypatch, capsys, "list")
    lines = [line for line in out.splitlines() if line.startswith("agent ")]
    assert code == 0 and " count=2 indices=2,3 running=0 " in lines[0]
    assert " count=2 running=0 " in lines[1] and " indices=" not in lines[1]


def test_adopt_sparse(env, monkeypatch):
    from hive import tmux
    agents_cfg(env, ("a", "indices = [2]"))
    # Legacy-tagged panes (`<prefix>-<type>-<N>`): only the desired index is adopted.
    listing = "%1\t@1\tt-a\tt-a-1\tt-a-1\n%2\t@1\tt-a\tt-a-2\tt-a-2\n"
    monkeypatch.setattr("hive.tmux.tmux", lambda cfg, *a, check=True: SimpleNamespace(
        returncode=0, stdout=listing, stderr=""))
    running, unmanaged = tmux.running_panes(load_config())
    assert list(running) == ["a-t-2"] and running["a-t-2"].adopted
    assert [u["pane"] for u in unmanaged] == ["%1"]


def test_stop_type_named_like_the_queen(env, monkeypatch, capsys):
    agents_cfg(env, ("hive-queen-t", "count = 2"))
    code, _, err = hive(monkeypatch, capsys, "stop", "hive-queen-t", "--index", "1")
    assert code == 0, err
    assert agent_entry(env, "hive-queen-t")["indices"] == [2]


def test_stop_instance_of_dot_type(env, monkeypatch, capsys):
    agents_cfg(env, (".a", "count = 2"))
    code, _, err = hive(monkeypatch, capsys, "stop", ".a-t-1")
    assert code == 0, err
    assert agent_entry(env, ".a")["indices"] == [2]


# --- agent systems: list, spawn --system, launchers, inspect-launcher (R1) -----------------

class ScreenTmux(FakeTmux):
    """capture-pane returns `screen`."""
    def __init__(self, screen=""):
        super().__init__()
        self.screen = screen

    def __call__(self, cfg, *args, check=True):
        super().__call__(cfg, *args, check=check)
        out = self.screen if args[0] == "capture-pane" else "%1\n"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")


def list_with_pane(env, monkeypatch, capsys, screen):
    agents_cfg(env, ("a", "count = 1"))
    monkeypatch.setattr("hive.tmux.session_running", lambda cfg: True)
    monkeypatch.setattr("hive.tmux.tmux", ScreenTmux(screen))
    pane = RunningPane("%5", "@0", "a-t", "a-t-1", "a", 1, False)
    monkeypatch.setattr("hive.tmux.running_panes", lambda cfg: ({"a-t-1": pane}, []))
    code, out, _ = hive(monkeypatch, capsys, "list")
    assert code == 0
    return out.splitlines()


def test_list_prints_system(env, monkeypatch, capsys):
    agents_cfg(env, ("a", "count = 1"))
    code, out, _ = hive(monkeypatch, capsys, "list")
    lines = out.splitlines()
    assert code == 0
    assert lines[1].startswith("queen ") and lines[1].endswith(" system=claude")
    agent = next(line for line in lines if line.startswith("agent "))
    assert " system=claude" in agent and "dir_missing" not in agent


def test_list_dir_missing_stays_last(env, monkeypatch, capsys):
    env.cfg.write_text(BASE + f'\n[[agents]]\ntype = "a"\ndir = "{env.tmp / "gone"}"\n')
    _, out, _ = hive(monkeypatch, capsys, "list")
    agent = next(line for line in out.splitlines() if line.startswith("agent "))
    assert agent.endswith(" system=claude dir_missing=yes")


def test_list_waiting_kind(env, monkeypatch, capsys):
    lines = list_with_pane(env, monkeypatch, capsys, "Select login method:\n")
    assert "pane name=a-t-1 type=a id=%5 system=claude waiting=login" in lines


def test_list_waiting_trust_unchanged(env, monkeypatch, capsys):
    lines = list_with_pane(env, monkeypatch, capsys, "Do you trust the files in this folder?\n")
    assert "pane name=a-t-1 type=a id=%5 system=claude waiting=trust" in lines
    lines = list_with_pane(env, monkeypatch, capsys, "all quiet\n")
    assert "pane name=a-t-1 type=a id=%5 system=claude" in lines


def spawn_dir(env):
    d = env.tmp / "w"
    d.mkdir(exist_ok=True)
    return str(d)


def test_spawn_system_flag(env, monkeypatch, capsys, fake_driver):
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--system", "fake",
                        "--command", "fake-agent")
    assert code == 0, err
    entry = agent_entry(env, "w")
    assert entry["system"] == "fake" and entry["command"] == "fake-agent"


def test_spawn_system_without_command_uses_driver_default(env, monkeypatch, capsys, fake_driver):
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--system", "fake")
    assert code == 0, err
    entry = agent_entry(env, "w")
    assert entry["system"] == "fake" and entry["command"] == type(fake_driver).default_command


def test_spawn_system_ignores_the_default_launcher(env, monkeypatch, capsys, fake_driver):
    env.cfg.write_text(BASE.replace("[defaults]", '[defaults]\nlauncher = "x"')
                       + '\n[[launchers]]\nname = "x"\ncommand = "run {name} --remote-control"\n')
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--system", "fake")
    assert code == 0, err
    entry = agent_entry(env, "w")
    assert entry["command"] == type(fake_driver).default_command and "config_dir" not in entry


def test_spawn_system_with_launcher_is_usage_error(env, monkeypatch, capsys, fake_driver):
    env.cfg.write_text(BASE + FAKE_LAUNCHER)
    before = env.cfg.read_bytes()
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--system", "fake",
                        "--launcher", "fk")
    assert code == 2 and "--launcher brings its own system" in err
    assert env.cfg.read_bytes() == before


def test_spawn_unknown_system(env, monkeypatch, capsys):
    before = env.cfg.read_bytes()
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--system", "nope")
    assert code == 2 and "unknown system 'nope'" in err
    assert env.cfg.read_bytes() == before


def test_spawn_system_differs_from_existing_type(env, monkeypatch, capsys, fake_driver):
    agents_cfg(env, ("a", "count = 1"))
    code, _, err = hive(monkeypatch, capsys, "spawn", "a", "--system", "fake")
    assert code == 2 and "runs system 'claude'" in err


def test_spawn_launcher_system_differs_from_existing_type(env, monkeypatch, capsys, fake_driver):
    # same command and config_dir as the launcher, but the type runs claude
    env.cfg.write_text(BASE + FAKE_LAUNCHER + f'\n[[agents]]\ntype = "w-fk"\ndir = "{spawn_dir(env)}"\n'
                       'command = "fake-agent --go"\n')
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--launcher", "fk")
    assert code == 2 and "runs system 'claude'" in err


FAKE_LAUNCHER = ('\n[[launchers]]\nname = "fk"\ncommand = "fake-agent --go"\n'
                 'system = "fake"\n')


def test_spawn_launcher_copies_system_and_checks_with_it(env, monkeypatch, capsys, fake_driver):
    env.cfg.write_text(BASE + FAKE_LAUNCHER)
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--launcher", "fk")
    assert code == 0, err
    entry = agent_entry(env, "w-fk")
    assert entry["system"] == "fake" and entry["command"] == "fake-agent --go"
    assert fake_driver.trust_calls == []  # trusted: nothing seeded, no exit 3


def test_system_precedence(env, monkeypatch, capsys, fake_driver):
    # a launcher's system beats [defaults] system; --system beats the default launcher
    env.cfg.write_text(BASE.replace("[defaults]", '[defaults]\nlauncher = "fk"') + FAKE_LAUNCHER)
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env))
    assert code == 0, err
    assert agent_entry(env, "w-fk")["system"] == "fake"
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--type", "plain",
                        "--system", "claude", "--command", "sleep 600 {name} --remote-control")
    assert code == 3, err  # untrusted claude dir exits 3 before any edit
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--type", "viafake",
                        "--system", "fake")
    assert code == 0, err
    assert agent_entry(env, "viafake")["system"] == "fake"


def test_spawn_probe_below_min(env, monkeypatch, capsys, fake_driver):
    fake_driver.min_version = (9, 0, 0)
    fake_bin(env.tmp, monkeypatch, "fake-agent", 'echo "fake 1.0.0"')
    before = env.cfg.read_bytes()
    code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--system", "fake")
    assert code == 2 and fake_driver.install_hint in err
    assert env.cfg.read_bytes() == before


def test_launchers_add_system(env, monkeypatch, capsys, fake_driver):
    fake_bin(env.tmp, monkeypatch, "fake-agent")
    code, _, err = hive(monkeypatch, capsys, "launchers", "add", "fk", "fake-agent --go",
                        "--system", "fake")
    assert code == 0, err
    launcher = tomllib.loads(env.cfg.read_text())["launchers"][0]
    assert launcher["system"] == "fake"
    _, out, _ = hive(monkeypatch, capsys, "launchers")
    assert " system=fake " in out
    code, _, err = hive(monkeypatch, capsys, "launchers", "add", "bad", "fake-agent",
                        "--system", "nope")
    assert code == 2 and "unknown system" in err


def test_launchers_add_default_system_writes_no_line(env, monkeypatch, capsys):
    fake_bin(env.tmp, monkeypatch, "claude")
    code, _, err = hive(monkeypatch, capsys, "launchers", "add", "c",
                        "claude -n {name} --remote-control")
    assert code == 0, err
    assert "system" not in tomllib.loads(env.cfg.read_text())["launchers"][0]
    _, out, _ = hive(monkeypatch, capsys, "launchers")
    assert " system=claude " in out


def test_inspect_launcher_system_flag(env, monkeypatch, capsys, fake_driver):
    root = env.tmp / "roots"
    root.mkdir()
    script = root / "fake-agent"
    script.write_text("#!/bin/sh\nexport FAKE_HOME=/somewhere\nexec true\n")
    script.chmod(0o755)
    env.cfg.write_text(f'inspect_roots = ["{root}"]\n' + BASE)
    code, out, err = hive(monkeypatch, capsys, "inspect-launcher", str(script),
                          "--system", "fake")
    assert code == 0, err
    assert "FAKE_HOME=/somewhere" in out
    code, _, err = hive(monkeypatch, capsys, "inspect-launcher", str(script), "--system", "nope")
    assert code == 2


def test_env_rejects_fake_config_dir_env(env, monkeypatch, capsys, fake_driver):
    for key in ("FAKE_HOME", "CLAUDE_CONFIG_DIR"):
        code, _, err = hive(monkeypatch, capsys, "spawn", spawn_dir(env), "--env", f"{key}=/x")
        assert code == 2 and f"--env {key}:" in err and "--config-dir or --launcher" in err
