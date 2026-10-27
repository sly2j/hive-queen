import ast
import os
import sys
from pathlib import Path

import pytest

from hive import cli, lock
from hive.config import cmd_init, load_config, profile_name
from hive.drivers.claude import DEFAULT_QUEEN_COMMAND, QUEEN_TOOLS
from hive.reconcile import desired_panes, parse_legacy_name, parse_name
from hive.service import unit_name
from hive.tmux import shell_line, tmux_env

BASE = """\
prefix = "t"

[defaults]
command = "claude -n {name} --remote-control {name}"
"""


QUEEN_FLAGS = f" --tools {QUEEN_TOOLS} --strict-mcp-config"


@pytest.fixture
def write(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def _write(text):
        path = tmp_path / "hive" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    return _write


def fails(capsys, text_in_error, code=2):
    with pytest.raises(SystemExit) as exc:
        load_config()
    assert exc.value.code == code
    err = capsys.readouterr().err
    assert err.startswith("hive: error: ")
    assert text_in_error in err


def test_1_5_config_loads_with_queen_defaults(write, tmp_path):
    write(BASE.replace('prefix = "t"\n', 'prefix = "swarm"\nsession = "swarm-agents"\n')
          + f'\n[env]\n# X = "y"\n\n[service]\nafter = ["a.service"]\n\n'
          f'[[agents]]\ntype = "obsidian"\ndir = "{tmp_path}"\ncount = 4\n')
    cfg = load_config()
    assert cfg["queen"] == {"type": "queen", "dir": str(tmp_path / "hive" / "queen"),
                            "command": "claude -n {name} --remote-control {name}" + QUEEN_FLAGS,
                            "args": [], "env": {},
                            "config_dir": None, "enabled": True, "system": "claude"}
    assert cfg["queen"]["command"] == cfg["agents"][0]["command"] + QUEEN_FLAGS
    assert cfg["search_roots"] == []
    assert cfg["discover"] is None
    assert cfg["config_path"] == str(tmp_path / "hive" / "config.toml")


def test_queen_table_and_search_roots(write, tmp_path):
    write(BASE + '\n[queen]\ncommand = "q {name} --remote-control"\ndiscover = "echo hi"\n')
    cfg = load_config()
    assert cfg["queen"]["command"] == "q {name} --remote-control" + QUEEN_FLAGS
    assert cfg["discover"] == "echo hi"


def test_search_roots_expanded(write):
    write('search_roots = ["~/work", "/srv"]\n' + BASE)
    roots = load_config()["search_roots"]
    assert roots[1] == "/srv"
    assert roots[0].endswith("/work") and "~" not in roots[0]


def test_search_roots_bad_type(write, capsys):
    write('search_roots = "~/work"\n' + BASE)
    fails(capsys, "search_roots must be an array of strings")
    write('search_roots = [1]\n' + BASE)
    fails(capsys, "search_roots must be an array of strings")


def test_queen_not_a_table(write, capsys):
    write('queen = "x"\n' + BASE)
    fails(capsys, "'queen' must be a table")


def test_queen_unknown_key(write, capsys):
    write(BASE + '\n[queen]\ncolour = "red"\n')
    fails(capsys, "unknown key 'colour' in [queen]")


def test_queen_discover_must_be_str(write, capsys):
    write(BASE + "\n[queen]\ndiscover = 3\n")
    fails(capsys, "'queen.discover' must be a string")


def test_queen_command_must_be_str(write, capsys):
    write(BASE + "\n[queen]\ncommand = 3\n")
    fails(capsys, "'queen.command' must be a string")


def test_queen_command_falls_back_to_builtin(write):
    write('prefix = "t"\n')
    assert load_config()["queen"]["command"] == DEFAULT_QUEEN_COMMAND + QUEEN_FLAGS


def test_queen_command_without_defaults(write):
    write('prefix = "t"\n[queen]\ncommand = "q"\n')
    assert load_config()["queen"]["command"] == "q" + QUEEN_FLAGS


def test_reserved_queen_type(write, capsys, tmp_path):
    write(BASE + f'\n[[agents]]\ntype = "queen"\ndir = "{tmp_path}"\n')
    fails(capsys, "agents[1].type 'queen' is reserved for the hive queen")


def test_count_zero_loads(write, tmp_path):
    write(BASE + f'\n[[agents]]\ntype = "a"\ndir = "{tmp_path}"\ncount = 0\n')
    assert load_config()["agents"][0]["count"] == 0


def test_count_negative(write, capsys, tmp_path):
    write(BASE + f'\n[[agents]]\ntype = "a"\ndir = "{tmp_path}"\ncount = -1\n')
    fails(capsys, "agents[1].count must be >= 0")


def test_empty_agents_loads(write):
    write(BASE)
    assert load_config()["agents"] == []
    write("agents = []\n" + BASE)
    assert load_config()["agents"] == []


def test_all_zero_counts_load(write, tmp_path):
    write(BASE + f'\n[[agents]]\ntype = "a"\ndir = "{tmp_path}"\ncount = 0\n'
          f'\n[[agents]]\ntype = "b"\ndir = "{tmp_path}"\ncount = 0\n')
    assert [a["count"] for a in load_config()["agents"]] == [0, 0]


def test_per_type_env_and_config_dir(write, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write(BASE + '\n[env]\nA = "g"\nB = "g"\n\n[queen]\nenv = { Q = "1" }\n'
          'config_dir = "~/.claude-q"\n'
          f'\n[[agents]]\ntype = "a"\ndir = "{tmp_path}"\nenv = {{ B = "t", C = "$HOME/x" }}\n'
          'config_dir = "/sandbox/cc"\n')
    cfg = load_config()
    assert cfg["queen"]["env"] == {"Q": "1"}
    assert cfg["queen"]["config_dir"] == str(tmp_path / ".claude-q")
    agent = cfg["agents"][0]
    assert agent["env"] == {"B": "t", "C": "$HOME/x"}
    assert agent["config_dir"] == "/sandbox/cc"
    line = shell_line(cfg, "/d", "run", agent["env"])
    assert line == ('export A="g" && export B="g" && export B="t" && export C="$HOME/x"'
                    ' && cd /d && run')
    # config_dir only locates the trust file; it is never exported
    assert "CLAUDE_CONFIG_DIR" not in line


def test_per_type_env_rejects_claude_config_dir(write, capsys, tmp_path):
    write(BASE + f'\n[[agents]]\ntype = "a"\ndir = "{tmp_path}"\n'
          'env = { CLAUDE_CONFIG_DIR = "/x" }\n')
    fails(capsys, "agents[1].env.CLAUDE_CONFIG_DIR: hive never sets CLAUDE_CONFIG_DIR")
    write(BASE + '\n[queen]\nenv = { CLAUDE_CONFIG_DIR = "/x" }\n')
    fails(capsys, "queen.env.CLAUDE_CONFIG_DIR")
    write(BASE + '\n[env]\nCLAUDE_CONFIG_DIR = "/x"\n')
    fails(capsys, "env.CLAUDE_CONFIG_DIR: hive never sets CLAUDE_CONFIG_DIR")


def test_config_dir_must_be_absolute(write, capsys, tmp_path):
    write(BASE + f'\n[[agents]]\ntype = "a"\ndir = "{tmp_path}"\nconfig_dir = "rel"\n')
    fails(capsys, "agents[1].config_dir 'rel' must be an absolute path or start with ~")


def test_per_type_env_value_must_be_str(write, capsys, tmp_path):
    write(BASE + f'\n[[agents]]\ntype = "a"\ndir = "{tmp_path}"\nenv = {{ X = 1 }}\n')
    fails(capsys, "agents[1].env.X must be a string")
    write(BASE + '\n[queen]\nenv = "x"\n')
    fails(capsys, "'queen.env' must be a table")


def test_init_writes_a_config_that_up_accepts(tmp_path, monkeypatch, capsys):
    # A fresh deploy: no project dirs exist, so the example must not reference any.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert cmd_init(None) == 0
    cfg = load_config()
    assert cfg["agents"] == []
    assert cfg["queen"]["command"] == DEFAULT_QUEEN_COMMAND + QUEEN_FLAGS
    assert [p.name for p in desired_panes(cfg)] == [f"hive-queen-{cfg['prefix']}"]
    assert cfg["launchers"] == [] and cfg["default_launcher"] is None


def test_env_names_are_checked(write, capsys):
    write(BASE + '\n[env]\n"A B" = "x"\n')
    fails(capsys, "env.A B: env names must match")


def test_missing_agent_dir_is_not_a_load_error(write, tmp_path):
    write(BASE + f'\n[[agents]]\ntype = "gone"\ndir = "{tmp_path / "gone"}"\n')
    assert load_config()["agents"][0]["type"] == "gone"


def test_parse_name_hyphenated_type():
    assert parse_name("t", "t-x-t-1") == ("t-x", 1)
    assert parse_name("t", "hive-queen-t") == ("queen", 1)
    # a user type `hive` does not collide with the queen
    assert parse_name("t", "hive-t-1") == ("hive", 1)
    # the queen is matched exactly, never by prefix
    assert parse_name("gpu07", "hive-queen-gpu07") == ("queen", 1)
    assert parse_name("gpu07", "hive-queen-gpu07-1") != ("queen", 1)
    # numeric and dotted prefixes
    assert parse_name("1", "a-1-2") == ("a", 2)
    assert parse_name("1", "hive-queen-1") == ("queen", 1)
    assert parse_name("g.1-x", "a-g.1-x-3") == ("a", 3)
    assert parse_name("t", "a-u-1") is None
    assert parse_name("t", "-t-1") is None


def test_parse_legacy_name():
    assert parse_legacy_name("t", "t-queen") == ("queen", 1)
    assert parse_legacy_name("t", "t-a-2") == ("a", 2)
    assert parse_legacy_name("t", "t-b-api-1") == ("b-api", 1)
    assert parse_legacy_name("t", "x-a-1") is None


def test_hive_type_names_distinct_from_queen(write, tmp_path):
    write(BASE + f'\n[[agents]]\ntype = "hive"\ndir = "{tmp_path}"\n')
    names = [p.name for p in desired_panes(load_config())]
    assert names == ["hive-queen-t", "hive-t-1"]


def test_hive_queen_type_reserved(write, capsys, tmp_path):
    write(BASE + f'\n[[agents]]\ntype = "hive-queen"\ndir = "{tmp_path}"\n')
    fails(capsys, "type 'hive-queen' is reserved for the hive queen")


def test_bad_prefix(write, capsys):
    write('prefix = "a b"\n')
    fails(capsys, "prefix")


LAUNCHERS = BASE + """
[[launchers]]
name = "a"
command = "claude -n {name} --remote-control {name}"

[[launchers]]
name = "b"
command = "cb -n {name} --remote-control {name}"
config_dir = "/cc/b"
description = "the b one"
"""


def run_hive(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["hive", *argv])
    try:
        code = cli.main()
    except SystemExit as e:
        code = e.code
    out, err = capsys.readouterr()
    return code, out.splitlines(), err


def test_launchers_parsed(write):
    write(LAUNCHERS)
    cfg = load_config()
    assert [l["name"] for l in cfg["launchers"]] == ["a", "b"]
    assert cfg["launchers"][1]["config_dir"] == "/cc/b"
    assert cfg["launchers"][1]["description"] == "the b one"
    assert cfg["launchers"][0]["config_dir"] is None
    assert cfg["default_launcher"] is None


def test_launcher_bad_name(write, capsys):
    write(BASE + '\n[[launchers]]\nname = "Bad Name"\ncommand = "c {name} --remote-control"\n')
    fails(capsys, "launchers[1].name 'Bad Name' must match")


def test_launcher_duplicate_name(write, capsys):
    block = '\n[[launchers]]\nname = "x"\ncommand = "c {name} --remote-control"\n'
    write(BASE + block + block)
    fails(capsys, "duplicate launcher name 'x'")


def test_launcher_command_needs_placeholders(write, capsys):
    write(BASE + '\n[[launchers]]\nname = "x"\ncommand = "c --remote-control"\n')
    fails(capsys, "launchers[1].command must contain {name} and --remote-control")
    write(BASE + '\n[[launchers]]\nname = "x"\ncommand = "c {name}"\n')
    fails(capsys, "must contain {name} and --remote-control")
    write(BASE + '\n[[launchers]]\nname = "x"\ncommand = "c {name} --remote-control"\nbogus = 1\n')
    fails(capsys, "bogus")


def test_default_launcher_unknown_registry_ok(write):
    write(BASE.replace("[defaults]\n", '[defaults]\nlauncher = "elsewhere"\n'))
    assert load_config()["default_launcher"] == "elsewhere"


def test_launchers_list_default_first(write, monkeypatch, capsys):
    write(LAUNCHERS.replace("[defaults]\n", '[defaults]\nlauncher = "b"\n'))
    for argv in (("launchers",), ("launchers", "list")):
        code, out, _ = run_hive(monkeypatch, capsys, *argv)
        assert code == 0
        assert out[0].startswith('launcher name="b" source=config default=yes system=claude config_dir="/cc/b" ')
        assert out[0].endswith('description="the b one"')
        assert out[1].startswith('launcher name="a" source=config default=no system=claude config_dir="default" ')


def discover_config(tmp_path, script):
    path = tmp_path / "discover.sh"
    path.write_text(f"#!/bin/sh\n{script}\n")
    path.chmod(0o755)
    return f'\n[queen]\ndiscover = "{path}"\n'


def test_launchers_list_includes_discover(write, tmp_path, monkeypatch, capsys):
    queen = discover_config(
        tmp_path, "echo 'name=x config_dir=/cc/x command=\"d {name} --remote-control\"'\n"
                  "echo 'name=a config_dir=/cc/a command=\"d2 {name} --remote-control\"'")
    write(LAUNCHERS + queen)
    code, out, _ = run_hive(monkeypatch, capsys, "launchers")
    assert code == 0
    assert [l.split()[1] for l in out] == ['name="a"', 'name="b"', 'name="x"', 'name="a"']
    assert "source=discover" in out[2] and "shadowed=yes" not in out[2]
    assert "source=discover" in out[3] and out[3].endswith("shadowed=yes")


def test_launchers_list_discover_error(write, tmp_path, monkeypatch, capsys):
    write(LAUNCHERS + discover_config(tmp_path, "echo boom >&2; exit 3"))
    code, out, _ = run_hive(monkeypatch, capsys, "launchers", "list")
    assert code == 0
    assert [l.split()[0] for l in out] == ["launcher", "launcher", "discover"]
    assert out[2].startswith('discover error="discover command failed (exit 3): boom')


def make_launcher(directory, name="mycl"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


CMD = "{} -n {{name}} --remote-control {{name}}"


def test_launchers_add_ok(write, tmp_path, monkeypatch, capsys):
    path = write(BASE)
    tool = make_launcher(tmp_path / "bin")
    code, out, _ = run_hive(monkeypatch, capsys, "launchers", "add", "mine", CMD.format(tool),
                            "--config-dir", "/cc/mine", "--description", "my one")
    assert code == 0 and out[0].startswith('launcher added name="mine" default=yes')
    cfg = load_config()
    assert cfg["default_launcher"] == "mine"
    assert cfg["launchers"][0]["config_dir"] == "/cc/mine"
    code, out, _ = run_hive(monkeypatch, capsys, "launchers", "add", "second", CMD.format(tool))
    assert code == 0 and "default=no" in out[0]
    assert load_config()["default_launcher"] == "mine"
    code, out, _ = run_hive(monkeypatch, capsys, "launchers")
    assert [l.split()[1] for l in out] == ['name="mine"', 'name="second"']
    assert path.read_text().startswith(BASE.replace("[defaults]\n", '[defaults]\nlauncher = "mine"\n'))


def test_launchers_add_symlink_outside_roots(write, tmp_path, monkeypatch, capsys):
    write(BASE)
    target = make_launcher(tmp_path / "elsewhere", "real-claude")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").symlink_to(target)
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    code, out, err = run_hive(monkeypatch, capsys, "launchers", "add", "viapath",
                              "claude -n {name} --remote-control {name}")
    assert code == 0, err
    assert [l["name"] for l in load_config()["launchers"]] == ["viapath"]


def test_launchers_add_duplicate(write, tmp_path, monkeypatch, capsys):
    queen = discover_config(
        tmp_path, "echo 'name=x config_dir=/cc/x command=\"d {name} --remote-control\"'")
    path = write(LAUNCHERS + queen)
    before = path.read_text()
    tool = make_launcher(tmp_path / "bin")
    for name in ("a", "x"):
        code, _, err = run_hive(monkeypatch, capsys, "launchers", "add", name, CMD.format(tool))
        assert code == 2 and "already exists" in err
    assert path.read_text() == before


def test_launchers_add_not_found(write, tmp_path, monkeypatch, capsys):
    path = write(BASE)
    before = path.read_text()
    code, _, err = run_hive(monkeypatch, capsys, "launchers", "add", "ghost",
                            CMD.format(tmp_path / "nope" / "claude"))
    assert code == 2 and "not found" in err
    assert path.read_text() == before


def test_launchers_add_private_refused(write, tmp_path, monkeypatch, capsys):
    path = write(BASE)
    before = path.read_text()
    tool = make_launcher(tmp_path / "private" / "bin")
    code, _, err = run_hive(monkeypatch, capsys, "launchers", "add", "secret", CMD.format(tool))
    assert code == 3 and "refused" in err
    assert path.read_text() == before


def test_launchers_default_set(write, tmp_path, monkeypatch, capsys):
    queen = discover_config(
        tmp_path, "echo 'name=x config_dir=/cc/x command=\"d {name} --remote-control\"'")
    write(LAUNCHERS + queen)
    for name in ("b", "x"):
        code, out, _ = run_hive(monkeypatch, capsys, "launchers", "default", name)
        assert code == 0 and out[0].startswith(f'default launcher="{name}"')
        assert load_config()["default_launcher"] == name


def test_launchers_default_unknown(write, monkeypatch, capsys):
    path = write(LAUNCHERS)
    before = path.read_text()
    code, _, err = run_hive(monkeypatch, capsys, "launchers", "default", "nope")
    assert code == 2 and "available: a, b" in err
    assert path.read_text() == before


# --- named profiles (R0) -------------------------------------------------------

def write_profile(tmp_path, name, text):
    path = tmp_path / "hive" / "profiles" / name / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """XDG_CONFIG_HOME = tmp_path; select a profile with the option (like --profile)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("hive.config._profile_option", None)

    def select(name):
        monkeypatch.setattr("hive.config._profile_option", name)
    return select


def test_profile_paths(profile, tmp_path, monkeypatch):
    profile("t")
    write_profile(tmp_path, "t", BASE)
    cfg = load_config()
    pdir = tmp_path / "hive" / "profiles" / "t"
    assert cfg["config_path"] == str(pdir / "config.toml")
    assert cfg["queen"]["dir"] == str(pdir / "queen")
    monkeypatch.setattr("hive.lock._lock", None)
    lock.hold_lock()
    lock._lock.close()
    assert (pdir / ".lock").exists() and not (tmp_path / "hive" / ".lock").exists()


def test_profile_env_vs_option(profile, monkeypatch):
    monkeypatch.setenv("HIVE_PROFILE", "a")
    assert profile_name() == "a"
    profile("b")
    assert profile_name() == "b"
    profile("default")
    assert profile_name() is None and unit_name() == "hive.service"


def test_profile_defaults(profile, tmp_path):
    profile("t")
    write_profile(tmp_path, "t", '[defaults]\ncommand = "c {name} --remote-control"\n')
    cfg = load_config()
    assert (cfg["prefix"], cfg["session"], cfg["socket"]) == ("t", "t-agents", "hive-t")
    assert cfg["profile"] == "t" and unit_name() == "hive-t.service"


@pytest.mark.parametrize("default_text", [None, 'tmux_socket = "prod"\n', "not toml [",
                                          'tmux_socket = "prod"\nprefix = "unterminated\n',
                                          '"tmux_socket" = "./prod"\nprefix = "unterminated\n'])
def test_profile_socket_collision(profile, tmp_path, capsys, default_text):
    if default_text is not None:
        (tmp_path / "hive").mkdir()
        (tmp_path / "hive" / "config.toml").write_text(default_text)
    profile("t")
    write_profile(tmp_path, "t", 'tmux_socket = "hive"\n' + BASE)
    fails(capsys, "is the default profile's socket")
    for alias in ("./hive", "/hive", "a/../hive"):
        write_profile(tmp_path, "t", f'tmux_socket = "{alias}"\n' + BASE)
        fails(capsys, "is the default profile's socket")
    if default_text and "prod" in default_text:
        write_profile(tmp_path, "t", 'tmux_socket = "prod"\n' + BASE)
        fails(capsys, "tmux_socket 'prod' is the default profile's socket")


def test_default_socket_alias_is_refused(profile, tmp_path, capsys):
    (tmp_path / "hive").mkdir()
    (tmp_path / "hive" / "config.toml").write_text(f'tmux_socket = "../tmux-{os.getuid()}/x"\n')
    profile("t")
    write_profile(tmp_path, "t", 'tmux_socket = "x"\n' + BASE)
    fails(capsys, "tmux_socket 'x' is the default profile's socket")


def test_unparsable_default_socket_line_is_refused(profile, tmp_path, capsys):
    (tmp_path / "hive").mkdir()
    (tmp_path / "hive" / "config.toml").write_text('tmux_socket = "prod\n')
    profile("t")
    write_profile(tmp_path, "t", BASE)
    fails(capsys, "cannot parse the tmux_socket line")


def test_invalid_profile_name(profile, capsys, monkeypatch):
    for bad in ("Bad.name", "-x", ""):
        monkeypatch.setattr(sys, "argv", ["hive", f"--profile={bad}", "list"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2
        assert "profile name" in capsys.readouterr().err


def test_pane_exports_profile(profile, tmp_path):
    profile("t")
    write_profile(tmp_path, "t", BASE + '\n[env]\nHIVE_PROFILE = "other"\n')
    line = shell_line(load_config(), "/d", "run")
    # last export wins, so a pane always addresses its own profile
    assert line.endswith("export HIVE_PROFILE=t && cd /d && run")
    profile(None)
    (tmp_path / "hive" / "config.toml").write_text(BASE)
    assert "HIVE_PROFILE" not in shell_line(load_config(), "/d", "run")


def test_tmux_server_env_drops_hive_profile(monkeypatch):
    monkeypatch.setenv("HIVE_PROFILE", "t")
    assert "HIVE_PROFILE" not in tmux_env()


def test_queen_enabled_must_be_bool(write, capsys):
    write(BASE + '\n[queen]\nenabled = "no"\n')
    fails(capsys, "'queen.enabled' must be true or false")


def test_fixtures_name_a_socket():
    """Config texts that tests run against real tmux name their own socket, and conftest
    points TMUX_TMPDIR at a private dir, so no test can reach the live hive server."""
    here = Path(__file__).parent
    # The base configs of the modules that start tmux (test_cli: a fake tmux on PATH).
    wanted = {("test_tmux.py", "CONFIG"), ("test_args.py", "CONFIG"), ("test_cli.py", "BASE")}
    texts = {}
    for path in here.glob("test_*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                key = (path.name, getattr(node.targets[0], "id", None))
                if key in wanted or key[1] == "CONFIG":
                    texts[key] = ast.unparse(node.value)
    assert wanted <= texts.keys()
    for name, text in texts.items():
        assert "tmux_socket" in text, name
    assert os.environ["TMUX_TMPDIR"].startswith("/tmp/hive-t-")


# --- [[nodes]] (R5) -------------------------------------------------------------

def test_nodes_parse_with_defaults(write):
    write(BASE + '\n[[nodes]]\nname = "swarm"\nhost = "me@swarm"\n\n'
          '[[nodes]]\nname = "pi-2"\nhost = "pi"\nhive = "/opt/hive"\nprofile = "test"\n'
          'description = "lab"\n')
    assert load_config()["nodes"] == [
        {"name": "swarm", "host": "me@swarm", "hive": "hive", "profile": None, "description": None},
        {"name": "pi-2", "host": "pi", "hive": "/opt/hive", "profile": "test", "description": "lab"}]


def test_no_nodes_is_empty(write):
    write(BASE)
    assert load_config()["nodes"] == []


@pytest.mark.parametrize("entry,error", [
    ('host = "h"', "missing required key 'name'"),
    ('name = "n"', "missing required key 'host'"),
    ('name = "Bad"\nhost = "h"', "must match"),
    ('name = "n"\nhost = "-oProxyCommand=x"', "not start with '-'"),
    ('name = "n"\nhost = "a b"', "no whitespace"),
    ('name = "n"\nhost = "h"\nhive = " "', "'nodes[1].hive' must not be empty"),
    ('name = "n"\nhost = "h"\nprofile = "Bad!"', "nodes[1].profile"),
    ('name = "n"\nhost = "h"\nport = 22', "unknown key 'port'"),
])
def test_node_validation(write, capsys, entry, error):
    write(BASE + f"\n[[nodes]]\n{entry}\n")
    fails(capsys, error)


def test_duplicate_node_name(write, capsys):
    write(BASE + '\n[[nodes]]\nname = "n"\nhost = "a"\n\n[[nodes]]\nname = "n"\nhost = "b"\n')
    fails(capsys, "duplicate node name 'n'")


def agent(extra="", type_="a", dir_="/a"):
    return f'\n[[agents]]\ntype = "{type_}"\ndir = "{dir_}"\n{extra}'


def test_env_rejects_every_config_dir_env(write, capsys, fake_driver):
    write(BASE + '\n[env]\nFAKE_HOME = "x"\n')
    fails(capsys, f"env.FAKE_HOME: {fake_driver.config_dir_env_msg}")
    write(BASE + agent('env = { FAKE_HOME = "x" }\n'))
    fails(capsys, f"agents[1].env.FAKE_HOME: {fake_driver.config_dir_env_msg}")
    write(BASE + '\n[env]\nCLAUDE_CONFIG_DIR = "x"\n')
    fails(capsys, "env.CLAUDE_CONFIG_DIR")


def test_queen_system_unsupported(write, capsys, fake_driver):
    write(BASE + '\n[queen]\nsystem = "fake"\n')
    fails(capsys, "queen.system 'fake' cannot run the queen")
    write(BASE + '\n[queen]\nsystem = "fake"\nenabled = false\n')
    assert load_config()["queen"]["system"] == "fake"


def test_parse_agents_non_default_system_without_command(write, fake_driver):
    write(BASE + agent('system = "fake"\n', "f") + agent("", "c"))
    agents = {a["type"]: a for a in load_config()["agents"]}
    assert agents["f"]["command"] == fake_driver.default_command
    assert agents["c"]["command"] == "claude -n {name} --remote-control {name}"
    write(BASE + agent('system = "fake"\ncommand = "mine {name}"\n', "f"))
    assert load_config()["agents"][0]["command"] == "mine {name}"


def test_system_precedence_in_config(write, fake_driver):
    write('prefix = "t"\n\n[defaults]\nsystem = "fake"\ncommand = "x {name}"\n\n'
          '[queen]\nenabled = false\n\n[[launchers]]\nname = "l"\ncommand = "l"\n'
          + agent("", "a") + agent('system = "claude"\ncommand = "claude -n {name} --remote-control {name}"\n', "b"))
    cfg = load_config()
    assert cfg["launchers"][0]["system"] == "fake"
    assert {a["type"]: a["system"] for a in cfg["agents"]} == {"a": "fake", "b": "claude"}
