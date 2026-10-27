"""Per-pane state: busy, done, blocked, dead, or the tmux-only quiet (docs/idle-detection.md).

Pure: reads and writes only files under cfg["state_dir"]; callers pass the tmux facts
(current command, screen text, session id), so this module never imports hive.tmux.
"""

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from hive.drivers import get_driver
from hive.reconcile import desired_panes

QUIET_AFTER = 30  # seconds of unchanged screen before the tmux fallback says quiet
SHELLS = frozenset({"sh", "bash", "zsh", "fish", "dash", "ksh"})
HOOK_STATES = frozenset({"busy", "done", "blocked", "dead"})


@dataclass(frozen=True)
class State:
    state: str
    source: str  # api | hook | tmux
    age: int  # seconds since the state was observed (api: 0)


def status_file(cfg, name):
    return Path(cfg["state_dir"]) / "status" / f"{name}.json"


def screen_file(cfg, name):
    return Path(cfg["state_dir"]) / "screens" / f"{name}.json"


def hook_cmd():
    """The status hook's argv prefix; sys.executable, as a bare python3 may be too old or absent."""
    return [sys.executable, str(files("hive") / "hooks" / "status_hook.py")]


def read_json(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path, data):
    """Atomic replace; a failure (read-only dir) is ignored: state is advisory."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)


def read_status(cfg, name):
    return read_json(status_file(cfg, name))


def reset_status(cfg, name):
    """Forget the previous launch's state, so a new pane never shows a stale file."""
    for path in (status_file(cfg, name), screen_file(cfg, name)):
        path.unlink(missing_ok=True)


def pane_map(cfg):
    """{pane name: Pane} over the desired panes; {} for a lenient config (no queen key)."""
    if "queen" not in cfg:
        return {}
    return {p.name: p for p in desired_panes(cfg)}


def shells(cfg):
    pane_shell = (cfg.get("pane_shell") or "").split()
    return SHELLS | {os.path.basename(pane_shell[0])} if pane_shell else SHELLS


def tmux_fallback(cfg, name, current_command, screen, now):
    """dead when the pane is back at its shell; quiet when the screen has not changed for
    QUIET_AFTER seconds (idle or blocked, so never done); else busy. The screen hash and the
    time it last changed persist in the screen file across one-shot calls."""
    digest = hashlib.sha256(screen.encode()).hexdigest()
    cached = read_json(screen_file(cfg, name))
    if cached and cached.get("hash") == digest and isinstance(cached.get("since"), (int, float)):
        since = cached["since"]
    else:
        since = now
        write_json(screen_file(cfg, name), {"hash": digest, "since": since})
    age = max(0, int(now - since))
    if current_command in shells(cfg):
        return State("dead", "tmux", age)
    return State("quiet" if age >= QUIET_AFTER else "busy", "tmux", age)


def pane_state(cfg, name, system, env, session_id, current_command, screen, now=None):
    """Driver poll first, then the hook's status file, then the tmux fallback."""
    now = time.time() if now is None else now
    polled = get_driver(system).poll_state(env, session_id)
    if polled is not None:
        return State(polled, "api", 0)
    record = read_status(cfg, name)
    if record and record.get("state") in HOOK_STATES:
        ts = record.get("ts")
        age = max(0, int(now - ts)) if isinstance(ts, (int, float)) else 0
        return State(record["state"], "hook", age)
    return tmux_fallback(cfg, name, current_command, screen, now)


def state_fields(state):
    return f"state={state.state} source={state.source} age={state.age}"
