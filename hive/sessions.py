"""Kept session ids (docs/resume.md): `<state_dir>/sessions.json`, one entry per instance name,
`{"session_id": id, "resume": bool}`.

`hive stop --keep-session` records the id an instance ran; `hive spawn TYPE --resume NAME` sets
`resume`, and the next launch of NAME (tmux.setup_pane) resumes that id once and drops the entry.
Pure like hive.activity: callers pass the tmux facts.
"""

import json
import os
from pathlib import Path

from hive.activity import read_json, read_status


def sessions_file(cfg):
    return Path(cfg["state_dir"]) / "sessions.json"


def load(cfg):
    """{name: entry} for the well-formed entries; {} when the file is missing or unreadable."""
    data = read_json(sessions_file(cfg)) or {}
    return {name: e for name, e in data.items()
            if isinstance(e, dict) and isinstance(e.get("session_id"), str) and e["session_id"]}


def save(cfg, data):
    """Atomic replace; unlike the advisory status files, a failure raises OSError."""
    path = sessions_file(cfg)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def record(cfg, ids):
    """Keep {name: session_id}, replacing earlier entries for those names."""
    data = load(cfg)
    data.update({name: {"session_id": sid, "resume": False} for name, sid in ids.items()})
    save(cfg, data)


def forget(cfg, names):
    data = load(cfg)
    if any(n in data for n in names):
        save(cfg, {k: v for k, v in data.items() if k not in names})


def mark_resume(cfg, name):
    data = load(cfg)
    data[name] = {**data[name], "resume": True}
    save(cfg, data)


def pending_resume(cfg, name):
    """The session id the next launch of `name` resumes, else None."""
    entry = load(cfg).get(name)
    return entry["session_id"] if entry and entry.get("resume") is True else None


def current_id(cfg, name, hive_session):
    """A pane's session id: the status file's (the hook saw it, so /clear is followed), else the
    `@hive_session` pane option set at launch, else None."""
    status = read_status(cfg, name) or {}
    sid = status.get("session_id")
    return sid if isinstance(sid, str) and sid else (hive_session or None)
