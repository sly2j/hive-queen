"""Claude Code: the default command, remote-control rule, trust and queen flags."""

import re

from hive.trust import is_trusted, looks_like_trust_prompt, seed_trust, trust_file, trust_root

# Used when neither [queen] nor [defaults] sets a command.
DEFAULT_QUEEN_COMMAND = "claude -n {name} --remote-control {name} --permission-mode auto"
# Tool allowlist for the queen; the guard hook enforces the same set.
QUEEN_TOOLS = "Bash,Monitor,Read,Grep,Glob,Edit,Write,NotebookEdit,AskUserQuestion"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
CONFIG_DIR_ENV_MSG = ("hive never sets CLAUDE_CONFIG_DIR (the launched command does); "
                      "use config_dir to name the dir for the trust check")
# Set by Claude Code for its child processes. A tmux server started from inside a
# Claude session would hand them to every pane, and claude in a pane would then
# think it is nested in that session. CLAUDE_CONFIG_DIR too: the launched command picks
# the config dir; an inherited one would load that session's settings (e.g. its "agent").
CLAUDE_SESSION_ENV = frozenset({"CLAUDE_CONFIG_DIR", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
                                "CLAUDE_CODE_SESSION_ID",
                                "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_BRIDGE_SESSION_ID",
                                "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
                                "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_EXECPATH",
                                "CLAUDE_CODE_SSE_PORT", "CLAUDE_PID", "CLAUDE_EFFORT"})
# Lines of a launcher script that `hive inspect-launcher` shows.
INSPECT_RE = re.compile(r"CLAUDE_CONFIG_DIR|claude|exec |env |export |HOME=|XDG_CONFIG_HOME",
                        re.IGNORECASE)


class ClaudeDriver:
    name = "claude"
    default_command = DEFAULT_QUEEN_COMMAND
    required_tokens = ("--remote-control",)
    env_scrub = CLAUDE_SESSION_ENV
    config_dir_env = CONFIG_DIR_ENV
    instructions_file = "CLAUDE.md"
    queen_files = {"CLAUDE.md": "CLAUDE.md", ".claude/settings.json": "settings.json",
                   ".claude/hooks/guard.py": "hooks/guard.py"}
    supports_queen = True
    inspect_pattern = INSPECT_RE

    def trust_state(self, directory, config_dir):
        """(trust root, trust file, trusted?) for a pane in `directory`."""
        root = trust_root(directory)
        return root, trust_file(config_dir), is_trusted(root, config_dir)

    def seed_trust(self, root, config_dir):
        seed_trust(root, config_dir)

    def looks_like_prompt(self, screen):
        return looks_like_trust_prompt(screen)

    def queen_extras(self, command, args=()):
        """The queen runs with a tool allowlist and no MCP servers, whatever command it got.

        Its args are placed into the command as whole shell-quoted words, so only an arg that is
        exactly the flag counts, not one whose text merely mentions it."""
        if not (re.search(r"(^|\s)--tools(\s|=|$)", command)
                or any(a == "--tools" or a.startswith("--tools=") for a in args)):
            command += f" --tools {QUEEN_TOOLS}"
        if not (re.search(r"(^|\s)--strict-mcp-config(\s|$)", command)
                or "--strict-mcp-config" in args):
            command += " --strict-mcp-config"
        return command
