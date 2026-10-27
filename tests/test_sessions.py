"""Resume (docs/resume.md): sessions.json, `stop --keep-session`, `spawn --resume`."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hive import cli, sessions
from hive.activity import status_file
from hive.config import load_config
from hive.launch import expand_pane
from hive.reconcile import RunningPane, desired_panes
from hive.tmux import setup_pane

ROOT = Path(__file__).resolve().parent.parent
UUID = "0b6f3c1e-1111-4222-8333-944455556666"
OTHER = "7d2a9e40-aaaa-4bbb-8ccc-ddddeeeeffff"
BASE = """\
prefix = "t"
tmux_socket = "hive-test-sessions-{pid}"

[defaults]
command = "claude -n {{name}} --remote-control {{name}}"

[[agents]]
type = "a"
dir = "{dir}"
count = 2
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setattr("hive.lock._lock", None)
    monkeypatch.setattr("hive.config._profile_option", None)
    (tmp_path / "a").mkdir()
    (Path(os.environ["HOME"]) / ".claude.json").write_text(json.dumps(
        {"projects": {str(tmp_path / "a"): {"hasTrustDialogAccepted": True}}}))
    path = xdg / "hive" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(BASE.format(pid=os.getpid(), dir=tmp_path / "a"))
    # Never reconcile against tmux here; the live test below does that.
    monkeypatch.setattr("hive.workers.reconcile_if_up", lambda cfg: 0)
    return SimpleNamespace(tmp=tmp_path, cfg=path)


def hive(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["hive", *argv])
    try:
        code = cli.main()
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    assert "Traceback" not in out.err
    return code, out.out, out.err


def write_status(cfg, name, session_id):
    path = status_file(cfg, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"state": "done", "session_id": session_id, "ts": time.time()}))


def fake_running(monkeypatch, name, hive_session):
    pane = RunningPane("%7", "@1", "a-t", name, "a", int(name.rsplit("-", 1)[1]), False)
    monkeypatch.setattr("hive.tmux.session_running", lambda cfg: True)
    monkeypatch.setattr("hive.tmux.running_panes", lambda cfg: ({name: pane}, []))
    monkeypatch.setattr("hive.workers.pane_facts", lambda cfg: {"%7": ("claude", hive_session)})


def test_record_and_load_roundtrip(env):
    cfg = load_config()
    sessions.record(cfg, {"a-t-1": UUID})
    assert sessions.load(cfg) == {"a-t-1": {"session_id": UUID, "resume": False}}
    assert sessions.pending_resume(cfg, "a-t-1") is None
    sessions.mark_resume(cfg, "a-t-1")
    assert sessions.pending_resume(cfg, "a-t-1") == UUID
    sessions.forget(cfg, ["a-t-1"])
    assert sessions.load(cfg) == {}


def test_state_file_under_profile_dir(env, monkeypatch):
    profile = env.cfg.parent / "profiles" / "test" / "config.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text(env.cfg.read_text().replace('prefix = "t"', 'prefix = "test"')
                       .replace("hive-test-sessions", "hive-test-prof"))
    monkeypatch.setenv("HIVE_PROFILE", "test")
    cfg = load_config()
    assert sessions.sessions_file(cfg) == profile.parent / "state" / "sessions.json"


def test_stop_keep_session_records_status_file_id(env, monkeypatch, capsys):
    cfg = load_config()
    write_status(cfg, "a-t-2", UUID)
    fake_running(monkeypatch, "a-t-2", OTHER)  # the status file wins over @hive_session
    code, out, err = hive(monkeypatch, capsys, "stop", "a", "--keep-session")
    assert code == 0, err
    assert sessions.load(cfg) == {"a-t-2": {"session_id": UUID, "resume": False}}
    assert f"kept session name=a-t-2 session={UUID}; resume with: hive spawn a --resume a-t-2" in out


def test_stop_keep_session_records_hive_session(env, monkeypatch, capsys):
    cfg = load_config()
    fake_running(monkeypatch, "a-t-1", UUID)
    code, _, err = hive(monkeypatch, capsys, "stop", "a-t-1", "--keep-session")
    assert code == 0, err
    assert sessions.load(cfg)["a-t-1"]["session_id"] == UUID


def test_stop_keep_session_without_id_changes_nothing(env, monkeypatch, capsys):
    before = env.cfg.read_text()
    code, _, err = hive(monkeypatch, capsys, "stop", "a", "--index", "1", "--keep-session")
    assert code == 1 and "no session id for a-t-1" in err
    assert env.cfg.read_text() == before and sessions.load(load_config()) == {}


def test_stop_forgets_without_keep(env, monkeypatch, capsys):
    cfg = load_config()
    sessions.record(cfg, {"a-t-1": UUID, "a-t-2": OTHER})
    code, _, err = hive(monkeypatch, capsys, "stop", "a", "--index", "1")
    assert code == 0, err
    assert set(sessions.load(cfg)) == {"a-t-2"}


def test_spawn_resume_puts_the_instance_back_and_marks_it(env, monkeypatch, capsys):
    cfg = load_config()
    write_status(cfg, "a-t-1", UUID)
    assert hive(monkeypatch, capsys, "stop", "a", "--index", "1", "--keep-session")[0] == 0
    code, out, err = hive(monkeypatch, capsys, "spawn", "a", "--resume", "a-t-1")
    assert code == 0, err
    assert "config agent=a count=1->2 file=" in out and f"resume name=a-t-1 session={UUID}" in out
    assert "count = 2" in env.cfg.read_text() and "indices" not in env.cfg.read_text()
    assert sessions.pending_resume(cfg, "a-t-1") == UUID
    _, out, _ = hive(monkeypatch, capsys, "list")
    assert f"kept name=a-t-1 session={UUID} resume=pending" in out


def test_resume_unknown_name(env, monkeypatch, capsys):
    before = env.cfg.read_text()
    code, _, err = hive(monkeypatch, capsys, "spawn", "a", "--resume", "a-t-3")
    assert code == 2 and "no kept session for 'a-t-3' (kept: none)" in err
    assert env.cfg.read_text() == before


@pytest.mark.parametrize("argv,text", [
    (["a", "--resume", "a-t-1"], "instance 'a-t-1' is configured already"),
    (["a", "--resume", "b-t-1"], "'b-t-1' is not an instance of type 'a'"),
    (["a", "--resume", "a-t-1", "-n", "2"], "do not combine it with -n"),
    (["a", "--resume", "a-t-1", "--arg=--fable"], "do not combine it with --arg"),
])
def test_resume_usage_errors(env, monkeypatch, capsys, argv, text):
    cfg = load_config()
    sessions.record(cfg, {"a-t-1": UUID, "b-t-1": OTHER})
    before = env.cfg.read_text()
    code, _, err = hive(monkeypatch, capsys, "spawn", *argv)
    assert code == 2 and text in err and env.cfg.read_text() == before
    assert sessions.pending_resume(cfg, "a-t-1") is None


def test_resume_unmarks_when_config_edit_fails(env, monkeypatch, capsys):
    cfg = load_config()
    sessions.record(cfg, {"a-t-3": UUID})

    def broken(*args, **kwargs):
        raise SystemExit(1)

    monkeypatch.setattr("hive.workers.set_indices_edit", broken)
    code, _, _ = hive(monkeypatch, capsys, "spawn", "a", "--resume", "a-t-3")
    assert code == 1 and sessions.pending_resume(cfg, "a-t-3") is None
    assert sessions.load(cfg)["a-t-3"]["session_id"] == UUID


def a_pane(**changes):
    cfg = load_config()
    return cfg, replace(desired_panes(cfg)[1], **changes)


def test_resume_args_at_args_placeholder(env, fake_driver):
    cfg, pane = a_pane(system="fake", command="fake-agent {args} --x", args=["--y"])
    assert expand_pane(cfg, pane, UUID, resume=True) == f"fake-agent resume {UUID} --y --x"


def test_resume_drops_session_id_flag(env):
    for command, args in [("claude -n {name} --remote-control {name} --session-id {session_id}",
                           []),
                          ("claude -n {name} --remote-control {name}",
                           ["--session-id={session_id}"]),
                          ("claude -n {name} --remote-control {name}",
                           ["--session-id", "{session_id}"]),
                          ('claude -n {name} --remote-control {name} --session-id "{session_id}"',
                           []),
                          ("claude -n {name} --remote-control {name} --session-id  {session_id}",
                           [])]:
        cfg, pane = a_pane(command=command, args=args)
        words = shlex.split(expand_pane(cfg, pane, UUID, resume=True))
        assert words[:8] == ["claude", "-n", "a-t-1", "--remote-control", "a-t-1",
                             "--resume", UUID, "--settings"], words
        assert not any(w.startswith("--session-id") for w in words)


def test_resume_keeps_hook_flags(env):
    cfg, pane = a_pane()
    words = shlex.split(expand_pane(cfg, pane, UUID, resume=True))
    settings = json.loads(words[words.index("--settings") + 1])
    assert str(status_file(cfg, "a-t-1")) in settings["hooks"]["Stop"][0]["hooks"][0]["command"]


def test_setup_pane_resumes_once(env, monkeypatch):
    cfg, pane = a_pane()
    sessions.record(cfg, {"a-t-1": UUID})
    sessions.mark_resume(cfg, "a-t-1")
    write_status(cfg, "a-t-1", OTHER)
    typed = []

    def fake(cfg, *args, check=True):
        if args[0] == "send-keys" and args[3] == "-l":
            typed.append(args[4])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("hive.tmux.tmux", fake)
    assert setup_pane(cfg, pane, "%1") == UUID
    assert f"--resume {UUID}" in typed[0] and "--session-id" not in typed[0]
    assert not status_file(cfg, "a-t-1").exists() and sessions.load(cfg) == {}
    assert setup_pane(cfg, pane, "%1") != UUID  # the next launch starts fresh
    assert "--session-id" in typed[1] and "--resume" not in typed[1]


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
def test_resume_without_hook_file_across_invocations(tmp_path):
    """stop --keep-session in one process, spawn --resume in another; no hook ever runs."""
    socket = f"hive-test-resume-{os.getpid()}"
    (tmp_path / "a").mkdir()
    cfg = tmp_path / "hive" / "config.toml"
    cfg.parent.mkdir()
    # Prints the flags hive appends ("$@"), then sleeps; never runs a hook.
    cfg.write_text(f"""\
prefix = "t"
session = "t-agents"
tmux_socket = "{socket}"
login_shell = false
shell = "/bin/sh"

[defaults]
command = "sh -c 'echo ARGS \\"$@\\" | cut -c1-120; exec sleep 600' {{name}} --remote-control"

[queen]
enabled = false

[[agents]]
type = "a"
dir = "{tmp_path / 'a'}"
count = 2
""")  # two panes: stopping the session's only pane would end the session
    (tmp_path / ".claude.json").write_text(json.dumps(
        {"projects": {str(tmp_path / "a"): {"hasTrustDialogAccepted": True}}}))
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path), "SHELL": "/bin/sh",
           "HOME": str(tmp_path)}

    def run(*args):
        return subprocess.run([sys.executable, "-m", "hive.cli", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True)

    def tmux(*args):
        return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, text=True)

    def pane_of(name):
        out = tmux("list-panes", "-s", "-t", "=t-agents", "-F",
                   "#{pane_id} #{@hive_name} #{@hive_session}").stdout
        return next((line.split() for line in out.splitlines() if f" {name} " in line), None)

    def screen(pane_id):
        for _ in range(50):
            text = tmux("capture-pane", "-p", "-J", "-t", pane_id).stdout
            if "ARGS --" in text:  # the output; the typed line has ARGS "$@"
                return text
            time.sleep(0.1)
        return text

    assert f"socket={socket}" in run("list").stdout.splitlines()[0]
    try:
        assert run("up").returncode == 0
        _, _, first_id = pane_of("a-t-1")
        status = tmp_path / "hive" / "state" / "status" / "a-t-1.json"
        assert not status.exists()
        r = run("stop", "a-t-1", "--keep-session")
        assert r.returncode == 0, r.stderr
        assert f"kept session name=a-t-1 session={first_id}" in r.stdout and pane_of("a-t-1") is None
        r = run("spawn", "a", "--resume", "a-t-1")
        assert r.returncode == 0, r.stderr
        assert "started a-t-1" in r.stdout
        pane_id, _, resumed_id = pane_of("a-t-1")
        assert resumed_id == first_id
        text = screen(pane_id)
        assert f"ARGS --remote-control --resume {first_id} --settings" in text
        assert "--session-id" not in text
        assert "kept " not in run("list").stdout  # consumed by the launch
    finally:
        tmux("kill-server")
