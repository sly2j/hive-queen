import json
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hive" / "hooks" / "status_hook.py"


def run(path, event, payload):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(HOOK), str(path), "--event", event], input=stdin,
                          capture_output=True, text=True)


def status(tmp_path, event, payload):
    path = tmp_path / "status.json"
    result = run(path, event, payload)
    assert result.returncode == 0
    return json.loads(path.read_text())


def test_status_hook_writes_file(tmp_path):
    rec = status(tmp_path, "Stop", {"session_id": "abc", "stop_hook_active": False})
    assert rec["state"] == "done" and rec["event"] == "Stop" and rec["session_id"] == "abc"
    assert rec["detail"] is None
    assert abs(rec["ts"] - time.time()) < 5


@pytest.mark.parametrize("event,payload,state,detail", [
    ("UserPromptSubmit", {"prompt": "hi"}, "busy", None),
    ("Stop", {"background_tasks": [{"id": "1"}], "session_crons": []}, "busy", None),
    ("Stop", {"background_tasks": [], "session_crons": [{"id": "1"}]}, "busy", None),
    ("Stop", {"background_tasks": [], "session_crons": []}, "done", None),
    ("Notification", {"notification_type": "permission_prompt"}, "blocked", "permission_prompt"),
    ("Notification", {"notification_type": "idle_prompt"}, "done", "idle_prompt"),
    ("Notification", {"notification_type": "agent_needs_input"}, "blocked", "agent_needs_input"),
    ("Notification", {"notification_type": "auth_success"}, "busy", "auth_success"),
    ("StopFailure", {"error": "rate_limit"}, "blocked", "rate_limit"),
    ("SessionEnd", {"reason": "logout"}, "dead", "logout"),
    ("SessionStart", {"source": "startup"}, "done", "startup"),
    ("SessionStart", {"source": 3}, "done", None),
])
def test_status_hook_mapping(tmp_path, event, payload, state, detail):
    rec = status(tmp_path, event, payload)
    assert (rec["state"], rec["detail"], rec["event"]) == (state, detail, event)


def test_status_hook_unknown_event(tmp_path):
    rec = status(tmp_path, "SomethingNew", {"session_id": "s"})
    assert rec["state"] == "busy" and rec["event"] == "SomethingNew"


@pytest.mark.parametrize("stdin", ["not json {", "", "[1, 2]", '{"session_id": 5}'])
def test_status_hook_bad_stdin(tmp_path, stdin):
    rec = status(tmp_path, "Stop", stdin)
    assert rec["state"] == "done" and rec["session_id"] is None


def test_status_hook_never_writes_stdout(tmp_path):
    assert run(tmp_path / "s.json", "Stop", {"session_id": "a"}).stdout == ""
    bad = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True, text=True)
    assert bad.returncode == 0 and bad.stdout == "" and bad.stderr
    blocked = tmp_path / "file"
    blocked.write_text("x")
    result = run(blocked / "sub" / "s.json", "Stop", {})
    assert result.returncode == 0 and result.stdout == "" and result.stderr


def test_status_hook_creates_dirs(tmp_path):
    path = tmp_path / "a" / "b" / "status.json"
    assert run(path, "Stop", {}).returncode == 0
    assert json.loads(path.read_text())["state"] == "done"


def test_status_hook_is_stdlib_only():
    imports = re.findall(r"^\s*(?:import|from)\s+(\S+)", HOOK.read_text(), re.M)
    assert imports and "hive" not in {i.split(".")[0] for i in imports}


def test_status_hook_is_package_data():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "hooks/*" in data["tool"]["setuptools"]["package-data"]["hive"]
