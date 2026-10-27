#!/usr/bin/env python3
"""Status hook for hive agents: maps a Claude hook event to a state and writes it to a file.

Usage: status_hook.py STATE_FILE --event NAME, with the hook JSON on stdin. Managed by hive.
Must stay stdlib-only (it runs under the agent's interpreter, with no hive import) and must always
exit 0 with nothing on stdout: Claude reads stdout, and a non-zero Stop hook can block stopping.
"""

import json
import os
import sys
import time

BLOCKING = {"permission_prompt", "agent_needs_input"}


def read_input():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _str(payload, key):
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _stop(payload):
    busy = any(isinstance(payload.get(k), list) and payload[k] for k in ("background_tasks", "session_crons"))
    return ("busy" if busy else "done"), None


def _notification(payload):
    kind = _str(payload, "notification_type")
    state = "blocked" if kind in BLOCKING else "done" if kind == "idle_prompt" else "busy"
    return state, kind


EVENTS = {
    "SessionStart": lambda p: ("done", _str(p, "source")),
    "UserPromptSubmit": lambda p: ("busy", None),
    "Stop": _stop,
    "StopFailure": lambda p: ("blocked", _str(p, "error")),
    "Notification": _notification,
    "SessionEnd": lambda p: ("dead", _str(p, "reason")),
}


def map_state(event, payload):
    return EVENTS.get(event, lambda p: ("busy", None))(payload)


def write_status(path, record):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(record, f)
    os.replace(tmp, path)


def main(argv):
    try:
        path, flag, event = argv[0], argv[1], argv[2]
        if flag != "--event":
            raise ValueError(f"expected --event, got {flag}")
        payload = read_input()
        state, detail = map_state(event, payload)
        write_status(path, {"state": state, "event": event, "session_id": _str(payload, "session_id"),
                            "ts": time.time(), "detail": detail})
    except Exception as e:
        print(f"status_hook: {e!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
