"""hive --node NAME: the ssh command line, the profile safety rule, exit codes, hive nodes.

ssh is never the real one: a fake `ssh` first on PATH logs its argv and exits with a set code.
"""

import shlex
import sys

import pytest

from hive import cli
from hive.nodes import node_argv, split_node_argv

NODES = """\
[[nodes]]
name = "swarm"
host = "swarm"
hive = "/home/u/.local/bin/hive"
profile = "test"

[[nodes]]
name = "prod"
host = "me@prod"
description = "production box"

[[nodes]]
name = "dflt"
host = "dflt"
profile = "default"
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("hive.config._profile_option", None)
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    default = xdg / "hive" / "config.toml"
    named = xdg / "hive" / "profiles" / "t" / "config.toml"
    for path in (default, named):
        path.parent.mkdir(parents=True)
        path.write_text(NODES)
    return tmp_path


def fake_ssh(tmp_path, monkeypatch, code=0):
    d = tmp_path / "bin"
    d.mkdir()
    log = d / "ssh.log"
    script = d / "ssh"
    script.write_text(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done > {log}\n'
                      f'echo remote-out\nexit {code}\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:/usr/bin:/bin")
    return log


def hive(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["hive", *argv])
    try:
        code = cli.main()
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    assert "Traceback" not in out.err
    return code, out.out, out.err


def node(**kw):
    return {"name": "swarm", "host": "swarm", "hive": "/home/u/.local/bin/hive",
            "profile": "test", "description": None, **kw}


def test_node_argv():
    assert node_argv(node(), "test", ["list"]) == [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "swarm", "--",
        "/home/u/.local/bin/hive --profile test list"]


def test_node_argv_quotes_for_the_remote_shell():
    remote = node_argv(node(), None, ["spawn", "~/my dir", "--env", "A=$HOME; rm -rf x"])[-1]
    assert shlex.split(remote)[3:] == ["spawn", "~/my dir", "--env", "A=$HOME; rm -rf x"]


@pytest.mark.parametrize("profile", [None, "default"])
def test_node_argv_default_remote_profile_sends_no_option(profile):
    assert node_argv(node(profile=profile), None, ["list"])[-1] == "/home/u/.local/bin/hive list"


@pytest.mark.parametrize("argv,expected", [
    (["--node", "swarm", "list"], ("swarm", None, ["list"])),
    (["--profile", "t", "--node=swarm", "stop", "a", "--profile", "x"],
     ("swarm", "t", ["stop", "a", "--profile", "x"])),
    (["--node", "swarm", "--profile", "t", "list"], ("swarm", None, ["--profile", "t", "list"])),
    (["--profile=t", "--node", "swarm", "--version"], ("swarm", "t", ["--version"])),
    (["--profile", "t", "list"], None),
    (["list", "--node", "swarm"], None),
    (["--node"], None),
])
def test_split_node_argv(argv, expected):
    assert split_node_argv(argv) == expected


def test_node_command_runs_ssh_and_passes_output(env, monkeypatch, capfd):
    log = fake_ssh(env, monkeypatch)
    code, out, _ = hive(monkeypatch, capfd, "--profile", "t", "--node", "swarm", "stop", "a b",
                        "--index", "2")
    assert (code, out) == (0, "remote-out\n")
    assert log.read_text().splitlines()[-1] == ("/home/u/.local/bin/hive --profile test stop "
                                                "'a b' --index 2")


def test_node_exit_code_passthrough(env, monkeypatch, capsys):
    fake_ssh(env, monkeypatch, code=3)
    assert hive(monkeypatch, capsys, "--node", "swarm", "spawn", "x")[0] == 3


def test_ssh_unreachable(env, monkeypatch, capsys):
    fake_ssh(env, monkeypatch, code=255)
    code, _, err = hive(monkeypatch, capsys, "--node", "swarm", "list")
    assert code == 1 and "node swarm unreachable" in err and "ssh swarm true" in err


@pytest.mark.parametrize("name", ["prod", "dflt"])
def test_node_default_profile_refused_from_named_profile(env, monkeypatch, capsys, name):
    log = fake_ssh(env, monkeypatch)
    code, _, err = hive(monkeypatch, capsys, "--profile", "t", "--node", name, "list")
    assert code == 2 and "may only reach a named remote profile" in err
    assert not log.exists()


def test_node_refused_from_hive_profile_env(env, monkeypatch, capsys):
    log = fake_ssh(env, monkeypatch)
    monkeypatch.setenv("HIVE_PROFILE", "t")
    assert hive(monkeypatch, capsys, "--node", "prod", "list")[0] == 2
    assert not log.exists()


def test_node_default_profile_allowed_from_default_profile(env, monkeypatch, capsys):
    log = fake_ssh(env, monkeypatch)
    assert hive(monkeypatch, capsys, "--node", "prod", "list")[0] == 0
    assert log.read_text().splitlines()[-3:] == ["me@prod", "--", "hive list"]


@pytest.mark.parametrize("argv,error", [
    (["attach"], "attach needs a terminal"),
    (["--profile", "prod", "down"], "put the subcommand right after"),
    (["--", "down"], "put the subcommand right after"),
    ([], "needs a subcommand"),
])
def test_node_usage_refused(env, monkeypatch, capsys, argv, error):
    log = fake_ssh(env, monkeypatch)
    code, _, err = hive(monkeypatch, capsys, "--node", "swarm", *argv)
    assert code == 2 and error in err
    assert not log.exists()


def test_unknown_node(env, monkeypatch, capsys):
    code, _, err = hive(monkeypatch, capsys, "--node", "nope", "list")
    assert code == 2 and "unknown node 'nope' (known: swarm, prod, dflt)" in err


def test_abbreviated_node_option_refused(env, monkeypatch, capsys):
    code, _, err = hive(monkeypatch, capsys, "--nod", "swarm", "list")
    assert code == 2 and "spell out --node" in err


def test_node_works_with_a_broken_config(env, monkeypatch, capsys):
    path = env / "xdg" / "hive" / "config.toml"
    path.write_text('bogus = 1\n' + NODES)
    fake_ssh(env, monkeypatch)
    assert hive(monkeypatch, capsys, "--node", "swarm", "list")[0] == 0


def test_nodes_list_output(env, monkeypatch, capsys):
    code, out, _ = hive(monkeypatch, capsys, "nodes")
    assert code == 0 and out.splitlines() == [
        'node name="swarm" host="swarm" hive="/home/u/.local/bin/hive" profile="test"',
        'node name="prod" host="me@prod" hive="hive" profile="default" '
        'description="production box"',
        'node name="dflt" host="dflt" hive="hive" profile="default"']
