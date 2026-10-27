"""The profile's command lock: one config- or session-editing hive command at a time."""

import fcntl
import time

from hive.config import profile_dir
from hive.util import die, warn

LOCK_WAIT = 30.0
_lock = None


def hold_lock(required=True):
    """Serialize commands that edit the config or the session, until exit.

    With required=False (`down`), a lock file that cannot be opened only warns:
    systemd's ExecStop must still be able to stop the session."""
    global _lock
    if _lock is not None:
        return
    path = profile_dir() / ".lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        f = open(path, "a")
    except OSError as e:
        if not required:
            warn(f"cannot open lock {path}: {e.strerror or e}; continuing without it")
            return
        die(f"cannot open lock {path}: {e.strerror or e}", 1)
    deadline = time.monotonic() + LOCK_WAIT
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() > deadline:
                die(f"another hive command holds {path}; try again", 1)
            time.sleep(0.1)
    _lock = f
