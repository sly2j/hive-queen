"""Codex CLI: the default command, trust in config.toml, the remote-control daemon.

Workers run in the user's default ~/.codex, the only home whose app-server daemon is paired with
the Codex and ChatGPT apps (docs/systems/codex.md). hive passes no -c overrides and no hook flags:
either one makes the TUI run embedded, off the shared daemon, so the app cannot see the pane.
Without hooks there is no status file and no session id; state comes from the tmux fallback.
"""

import json
import os
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path

from hive.drivers.common import match_waiting, probe_version
from hive.paths import expanduser
from hive.trust import TrustError, trust_root
from hive.util import warn

# {args} first, so resume args (`resume <id>`) land right after the binary.
DEFAULT_COMMAND = "codex {args} -a never -s workspace-write"
CONFIG_DIR_ENV = "CODEX_HOME"
CONFIG_DIR_ENV_MSG = ("hive never sets CODEX_HOME (the launched command does); use config_dir to "
                      "name the dir for the trust check; only the default ~/.codex reaches the "
                      "paired remote-control daemon")
INSPECT_RE = re.compile(r"CODEX_HOME|codex|exec |env |export |HOME=", re.IGNORECASE)
TRUSTED = "trusted"

_daemon_checked = False  # ensure_daemon runs once per hive process


def codex_home(config_dir=None):
    """The pane's CODEX_HOME: config_dir, else the default ~/.codex (hive scrubs CODEX_HOME)."""
    return expanduser(config_dir) if config_dir else Path.home() / ".codex"


def toml_str(text):
    """A TOML basic string; JSON string escapes are valid TOML ones."""
    return json.dumps(str(text), ensure_ascii=False)


def read_toml(path):
    """The parsed file, {} when absent; TrustError when it cannot be read or parsed."""
    try:
        return tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise TrustError(f"{path}: cannot parse ({e}); not touching it") from None


def trust_level(data, root):
    projects = data.get("projects")
    entry = projects.get(str(root)) if isinstance(projects, dict) else None
    return entry.get("trust_level") if isinstance(entry, dict) else None


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def seed_trust(root, config_dir=None):
    """Append `[projects."<root>"] trust_level = "trusted"` to <CODEX_HOME>/config.toml.

    Never edits existing TOML: an existing table for root with another level, or a file that does
    not parse (before or after the append), is refused and the file left as it was; the
    appended text is parsed before it is written."""
    path = codex_home(config_dir) / "config.toml"
    data = read_toml(path)
    level = trust_level(data, root)
    if level == TRUSTED:
        return
    if isinstance(data.get("projects"), dict) and str(root) in data["projects"]:
        raise TrustError(f"{path}: [projects.{toml_str(root)}] exists with trust_level = "
                         f"{level!r}; set it to \"trusted\" there yourself")
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    sep = "" if not old or old.endswith("\n") else "\n"
    new = f"{old}{sep}\n[projects.{toml_str(root)}]\ntrust_level = \"trusted\"\n"
    try:
        ok = trust_level(tomllib.loads(new), root) == TRUSTED
    except tomllib.TOMLDecodeError:
        ok = False
    if not ok:
        raise TrustError(f"{path}: appending a [projects] table would not parse as trusted; "
                         "left unchanged")
    write_atomic(path, new)


def _alive(pid, start_ticks):
    """pid runs, and on Linux is the process the pid file describes (start time in ticks)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        try:
            os.kill(pid, 0)  # EPERM: another user's process, not this user's daemon
        except OSError:
            return False
        return True
    if start_ticks is None:
        return True
    fields = stat.rpartition(")")[2].split()
    return len(fields) > 19 and fields[19] == str(start_ticks)


def _cmdline(pid):
    """The argv of pid from /proc, None where there is no /proc."""
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0")
    except OSError:
        return None


def daemon_state(home):
    """"remote" (live daemon with remote control), "plain" (live without), or None (absent).

    Remote control shows as `--remote-control` in the daemon's /proc cmdline, else (no /proc) as
    `remoteControlEnabled` in app-server-daemon/settings.json (both seen on Codex 0.164/0.165)."""
    state_dir = home / "app-server-daemon"
    try:
        info = json.loads((state_dir / "daemon.pid").read_text())
        pid = int(info["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    ident = info.get("processIdentity")
    ticks = ident.get("startTicks") if isinstance(ident, dict) else None
    if pid <= 0 or not _alive(pid, ticks):
        return None
    argv = _cmdline(pid)
    if argv is not None:
        return "remote" if "--remote-control" in argv else "plain"
    try:
        settings = json.loads((state_dir / "settings.json").read_text())
    except (OSError, ValueError):
        settings = {}
    return "remote" if isinstance(settings, dict) and settings.get("remoteControlEnabled") is True \
        else "plain"


def ensure_daemon(env, binary="codex"):
    """Once per process: start the default home's daemon with remote control when none runs.

    A running daemon is never stopped or restarted; one without remote control only gets a
    warning, since whether `start` is safe on a running daemon is unverified."""
    global _daemon_checked
    if _daemon_checked:
        return
    _daemon_checked = True
    home = codex_home()
    state = daemon_state(home)
    if state == "remote":
        return
    if state == "plain":
        warn("the Codex daemon of ~/.codex runs without remote control, so Codex panes will not "
             "show in the Codex app; run 'codex remote-control start' after closing your own "
             "Codex sessions (hive never restarts a running daemon)")
        return
    run_env = {k: v for k, v in os.environ.items() if k != CONFIG_DIR_ENV} | dict(env)
    try:
        out = subprocess.run([binary, "remote-control", "start"], env=run_env,
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        warn(f"cannot start the Codex remote-control daemon ({binary} remote-control start): {e}")
        return
    if out.returncode != 0:
        detail = (out.stderr or out.stdout).strip().splitlines()[-1:] or [f"exit {out.returncode}"]
        warn(f"'{binary} remote-control start' failed: {detail[0]}; Codex panes will not show in "
             "the Codex app until it runs")


class CodexDriver:
    name = "codex"
    default_command = DEFAULT_COMMAND
    required_tokens = ()
    required_placeholders = ()
    # An inherited CODEX_HOME would move every pane off the paired default home.
    env_scrub = frozenset({CONFIG_DIR_ENV})
    config_dir_env = CONFIG_DIR_ENV
    config_dir_env_msg = CONFIG_DIR_ENV_MSG
    instructions_file = "AGENTS.md"
    queen_files = {}
    supports_queen = False
    inspect_pattern = INSPECT_RE
    assigns_session_id = False  # Codex picks its own id; hive cannot read it in this release
    keep_session_msg = ("codex: session capture not supported in this release; use "
                        "`codex resume` inside a new pane")
    binary = "codex"
    min_version = (0, 164, 0)
    install_hint = "npm install -g @openai/codex"
    versions = ("0.164.0",)
    waiting_kinds = (("trust", ("trust this folder?",)),
                     ("hooks_review", ("hooks need review",)),
                     ("login", ("sign in with chatgpt", "choose how you want to use codex")))

    def trust_state(self, directory, config_dir):
        """(trust root, config.toml, trusted?) for a pane in `directory`. Codex asks only inside
        a git work tree (verified on 0.164.0), so a dir outside one counts as trusted."""
        root = trust_root(directory)
        path = codex_home(config_dir) / "config.toml"
        if not (root / ".git").exists():
            return root, path, True
        try:
            trusted = trust_level(read_toml(path), root) == TRUSTED
        except TrustError:
            trusted = False
        return root, path, trusted

    def seed_trust(self, root, config_dir):
        seed_trust(root, config_dir)

    def waiting_kind(self, screen):
        return match_waiting(self.waiting_kinds, screen)

    def probe(self, binary):
        return probe_version(binary)

    def session_args(self, session_id):
        return []  # Codex has no flag to choose the id

    def resume_args(self, session_id):
        return ["resume", session_id]

    def hook_args(self, hook_cmd, state_file):
        # -c and --dangerously-bypass-hook-trust each force embedded mode on 0.164.0 ("Running
        # without the shared background server: ... requires embedded mode"), off the daemon.
        return []

    def poll_state(self, env, session_id):
        return None  # no API to poll and no hooks: the tmux fallback decides

    def prepare_launch(self, env, pane):
        """Ensure the default home's daemon for a pane in that home; Codex picks the id."""
        if not pane.config_dir:
            ensure_daemon(env, self.binary)
        return None

    def queen_extras(self, command, args=()):
        return command  # no Codex queen in this release (supports_queen is False)

