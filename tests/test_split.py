"""Guards for the module split of hive/cli.py: identical --help, the import graph, the driver seam."""

import ast
import contextlib
import io
import os
import pkgutil
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import hive
from hive import cli
from hive.config import load_config
from hive.drivers import get_driver
from hive.drivers.claude import DEFAULT_QUEEN_COMMAND, QUEEN_TOOLS

ROOT = Path(__file__).resolve().parent.parent

DATA = Path(__file__).parent / "data"
HELP_COMMANDS = [[], ["up"], ["down"], ["restart"], ["status"], ["attach"], ["list"], ["spawn"],
                 ["stop"], ["reconcile"], ["launchers"], ["launchers", "list"],
                 ["launchers", "add"], ["launchers", "default"], ["discover"], ["dirs"], ["roots"],
                 ["inspect-launcher"], ["init"], ["install-service"], ["uninstall-service"]]


def help_text():
    """Every parser's --help, one section per command."""
    out = []
    for argv in HELP_COMMANDS:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
            cli.build_parser().parse_args([*argv, "--help"])
        out.append(f"=== hive {' '.join(argv)} --help\n{buf.getvalue()}")
    return "".join(out)


def golden_path():
    # argparse output differs between Python minor versions (3.13 shortened alias metavars).
    return DATA / f"help-{sys.version_info.major}.{sys.version_info.minor}.txt"


def test_cli_help_unchanged(monkeypatch):
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("PYTHON_COLORS", "0")
    path = golden_path()
    if not path.exists():
        pytest.skip(f"no golden help for Python {sys.version_info.major}.{sys.version_info.minor}")
    assert help_text() == path.read_text()



def hive_modules():
    return sorted(m.name for m in pkgutil.walk_packages(hive.__path__, "hive."))


def test_no_import_cycles():
    """Each module imports on its own (a cycle fails for whichever module is imported first)."""
    for name in hive_modules():
        result = subprocess.run([sys.executable, "-c", f"import {name}"], capture_output=True,
                                text=True)
        assert result.returncode == 0, f"{name}: {result.stderr}"


def hive_imports(path):
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    return {n for n in found if n == "hive" or n.startswith("hive.")}


@pytest.mark.parametrize("module", ["util.py", "paths.py"])
def test_util_imports_nothing_from_hive(module):
    assert hive_imports(ROOT / "hive" / module) == set()


def test_guard_is_standalone():
    assert hive_imports(ROOT / "hive" / "queen" / "hooks" / "guard.py") == set()


def test_nothing_imports_cli():
    users = [p.name for p in (ROOT / "hive").rglob("*.py") if "hive.cli" in hive_imports(p)
             or any(isinstance(n, ast.alias) and n.name == "cli"
                    for n in ast.walk(ast.parse(p.read_text())))]
    assert users == []


def test_driver_claude_matches_constants():
    driver = get_driver("claude")
    assert driver.default_command == DEFAULT_QUEEN_COMMAND == (
        "claude -n {name} --remote-control {name} --permission-mode auto")
    assert driver.required_tokens == ("--remote-control",)
    base = "claude -n {name} --remote-control {name}"
    assert driver.queen_extras(base, []) == (
        f"{base} --tools {QUEEN_TOOLS} --strict-mcp-config")
    assert QUEEN_TOOLS == "Bash,Monitor,Read,Grep,Glob,Edit,Write,NotebookEdit,AskUserQuestion"
    with pytest.raises(ValueError, match="known: claude"):
        get_driver("x")


SYSTEM_CONFIG = """\
tmux_socket = "hive-test-split"

[defaults]
command = "claude -n {{name}} --remote-control {{name}}"
system = "{defaults}"

[queen]
system = "{queen}"

[[launchers]]
name = "c"
command = "claude -n {{name}} --remote-control {{name}}"
system = "{launcher}"

[[agents]]
type = "a"
dir = "{dir}"
system = "{agent}"
"""


def write_system_config(tmp_path, **systems):
    levels = {"defaults": "claude", "queen": "claude", "launcher": "claude", "agent": "claude",
              **systems}
    path = Path(os.environ["XDG_CONFIG_HOME"]) / "hive" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SYSTEM_CONFIG.format(dir=tmp_path, **levels))


def test_system_key(tmp_path, capsys):
    write_system_config(tmp_path)
    cfg = load_config()
    assert cfg["system"] == cfg["queen"]["system"] == cfg["agents"][0]["system"] == "claude"
    assert cfg["launchers"][0]["system"] == "claude"
    for level, key in [("defaults", "defaults.system"), ("queen", "queen.system"),
                       ("launcher", "launchers[1].system"), ("agent", "agents[1].system")]:
        write_system_config(tmp_path, **{level: "x"})
        with pytest.raises(SystemExit) as exc:
            load_config()
        err = capsys.readouterr().err
        assert exc.value.code == 2
        assert f"'{key}' = 'x' is not a known system (known: claude)" in err


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_wheel_has_drivers(tmp_path):
    """The built wheel ships hive.drivers (an explicit setuptools packages list) and the entry point."""
    dist = tmp_path / "dist"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(dist), str(ROOT)], check=True,
                   capture_output=True)
    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", "--python", sys.executable, str(venv)], check=True,
                   capture_output=True)
    python = venv / "bin" / "python"
    wheel = next(dist.glob("*.whl"))
    subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)], check=True,
                   capture_output=True)
    # Run outside the checkout so the source tree cannot shadow the installed package.
    out = subprocess.run([str(python), "-c", "import hive.drivers.claude, hive.cli, hive.queen; "
                          "from importlib import resources; "
                          "assert resources.files('hive').joinpath('queen', 'hooks', 'guard.py')"
                          ".is_file(); print(hive.cli.__file__)"], cwd=tmp_path, capture_output=True,
                         text=True, check=True).stdout
    assert str(venv) in out
    version = subprocess.run([str(venv / "bin" / "hive"), "--version"], cwd=tmp_path,
                             capture_output=True, text=True, check=True).stdout
    assert version.startswith("hive ")


if __name__ == "__main__":
    # Regenerate the golden file for this Python: COLUMNS=100 NO_COLOR=1 python tests/test_split.py
    golden_path().write_text(help_text())
