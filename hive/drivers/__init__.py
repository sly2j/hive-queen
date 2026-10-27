"""Agent systems hive can run in a pane (config key `system`); each driver holds what is
specific to one system. Only `claude` exists so far."""

from typing import Protocol

from hive.drivers.claude import ClaudeDriver


class Driver(Protocol):
    name: str
    default_command: str  # the queen's command when neither [queen] nor [defaults] sets one
    required_tokens: tuple[str, ...]  # a launcher command must contain each one
    env_scrub: frozenset[str]  # never passed from hive's environment to the tmux server
    config_dir_env: str | None  # the system's config-dir variable; hive never sets it
    instructions_file: str  # the queen's instructions file, relative to the queen dir
    queen_files: dict[str, str]  # queen dir path -> packaged file under hive/queen/
    supports_queen: bool
    assigns_session_id: bool  # hive passes its own uuid at launch
    binary: str  # the executable whose --version is probed
    min_version: tuple[int, ...] | None  # oldest supported version, None = no floor
    install_hint: str  # shown when the binary is missing
    versions: tuple[str, ...]  # versions this driver was verified on
    required_placeholders: tuple[str, ...]  # a launcher command must contain each one
    config_dir_env_msg: str | None  # why hive never sets config_dir_env
    waiting_kinds: tuple[tuple[str, tuple[str, ...]], ...]  # (kind, screen phrases)

    def trust_state(self, directory, config_dir): ...  # (trust root, trust file, trusted?)
    def seed_trust(self, root, config_dir): ...
    def waiting_kind(self, screen): ...  # the first waiting kind the screen shows, else None
    def probe(self, binary): ...  # installed version "X.Y.Z", None when missing/unparseable
    def session_args(self, session_id): ...  # flags that start a session with this id
    def resume_args(self, session_id): ...  # flags that resume that session
    def hook_args(self, hook_cmd, state_file): ...  # flags wiring lifecycle hooks to state_file
    def poll_state(self, env, session_id): ...  # current state from the system's own API, else None
    def prepare_launch(self, env, pane): ...  # session id the system chose itself, else None
    def queen_extras(self, command, args): ...  # command plus the queen's restricting flags


DRIVERS = {"claude": ClaudeDriver()}
DEFAULT_SYSTEM = "claude"
KNOWN_SYSTEMS = ("claude", "opencode", "codex")


def get_driver(name):
    try:
        return DRIVERS[name]
    except KeyError:
        if name in KNOWN_SYSTEMS:
            raise ValueError(f"system {name!r} is not in this release "
                             f"(available: {', '.join(DRIVERS)})") from None
        raise ValueError(f"unknown system {name!r} (known: {', '.join(DRIVERS)})") from None


def config_dir_envs():
    """Config-dir variable -> why hive never sets it, over the registered drivers."""
    return {d.config_dir_env: d.config_dir_env_msg for d in DRIVERS.values() if d.config_dir_env}
