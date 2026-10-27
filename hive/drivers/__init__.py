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

    def trust_state(self, directory, config_dir): ...  # (trust root, trust file, trusted?)
    def seed_trust(self, root, config_dir): ...
    def looks_like_prompt(self, screen): ...  # True when the screen shows the trust prompt
    def queen_extras(self, command, args): ...  # command plus the queen's restricting flags


DRIVERS = {"claude": ClaudeDriver()}
DEFAULT_SYSTEM = "claude"


def get_driver(name):
    try:
        return DRIVERS[name]
    except KeyError:
        raise ValueError(f"unknown system {name!r} (known: {', '.join(DRIVERS)})") from None
