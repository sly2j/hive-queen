"""Fake agent for live checks: runs the hook commands from --settings, then sleeps.

Usage: FAKE_EVENTS="SessionStart UserPromptSubmit:3 Stop:6" fake_worker.py NAME --remote-control X \
    --session-id ID --settings JSON
Items are `Event`, `Event:T` or `Notification:TYPE:T` (T = seconds after start). Other args are ignored.
"""

import json
import os
import re
import subprocess
import sys
import time

DEFAULT_EVENTS = "SessionStart UserPromptSubmit:3 Stop:6"


def parse_args(argv):
    name = argv[0] if argv and not argv[0].startswith("-") else "fake"
    opts = {}
    for i, arg in enumerate(argv):
        if arg in ("--session-id", "--settings") and i + 1 < len(argv):
            opts[arg] = argv[i + 1]
    return name, opts


def parse_item(item):
    parts = item.split(":")
    event, kind, offset = parts[0], None, 0.0
    if event == "Notification" and len(parts) > 1:
        kind = parts[1]
        parts = parts[2:]
    else:
        parts = parts[1:]
    if parts:
        offset = float(parts[0])
    return event, kind, offset


def payload(event, kind, session_id):
    data = {"session_id": session_id, "hook_event_name": event, "cwd": os.getcwd()}
    if event == "SessionStart":
        data["source"] = "startup"
    elif event == "UserPromptSubmit":
        data["prompt"] = "fake prompt"
    elif event == "Stop":
        data.update(stop_hook_active=False, last_assistant_message="",
                    background_tasks=[], session_crons=[])
    elif event == "Notification":
        data.update(notification_type=kind, message=f"fake {kind}")
    elif event == "SessionEnd":
        data["reason"] = "other"
    return data


def commands(settings, event, kind):
    for entry in settings.get("hooks", {}).get(event, []):
        matcher = entry.get("matcher")
        if event == "Notification" and matcher and not re.fullmatch(matcher, kind or ""):
            continue
        for hook in entry.get("hooks", []):
            if hook.get("type") == "command":
                yield hook["command"]


def main(argv):
    name, opts = parse_args(argv)
    session_id = opts.get("--session-id")
    settings = json.loads(opts["--settings"]) if "--settings" in opts else {}
    start = time.monotonic()
    for item in os.environ.get("FAKE_EVENTS", DEFAULT_EVENTS).split():
        event, kind, offset = parse_item(item)
        time.sleep(max(0.0, start + offset - time.monotonic()))
        print(f"fake {name}: {event}", flush=True)
        body = json.dumps(payload(event, kind, session_id))
        for cmd in commands(settings, event, kind):
            subprocess.run(cmd, shell=True, input=body, text=True)
    os.execvp("sleep", ["sleep", "1d"])


if __name__ == "__main__":
    main(sys.argv[1:])
