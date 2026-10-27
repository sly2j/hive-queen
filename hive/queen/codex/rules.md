## Workspace trust

- Codex asks to trust a folder that is a git work tree or has its own `.codex/` dir; the decision lives in `~/.codex/config.toml` (`trust_file=` in `hive list`).
- `hive spawn` exits 3 and prints `untrusted: ...` when Codex does not trust the directory. Tell the user the exact directory, the trust root and the trust file from the message. Say that trusting enables that folder's `.codex/` config, hooks and rules.
- You cannot run `hive spawn --trust` (the guard denies it, see Rules): tell the user to run the same spawn command with `--trust` added by hand, or to attach to the pane and accept Codex's trust prompt.
- If `hive list` shows a `pane ... waiting=trust` or `waiting=hooks_review` record, tell the user which pane is waiting and that they must run `hive attach` to answer the prompt there.

## Rules

- There is no question tool: list numbered choices in plain text and act only on an explicit pick.
- Use only the shell tool, and run only a single `hive ...` command: no `;`, `&`, `|`, backticks, `$(`, redirects or newlines. Path arguments may not use globs or brace expansion (`{a,b}`, `{1..3}`) or point under a `secrets`/`private` path. Put no options before the subcommand (`hive -- down` is blocked); only `hive --version`, `-h`, `--help` and `--node NAME` are allowed there. A guard hook denies every other command and tool except `update_plan`; to read anything, use `hive` commands.
- `apply_patch` works only inside your own directory, never under a `secrets`/`private` path, and never on `AGENTS.md`, `AGENTS.override.md` or `.codex/`. hive owns this `AGENTS.md`; local additions go in the user's own `~/.codex/AGENTS.md`, not here.
- Codex cannot show the user a confirmation prompt, so the guard denies these calls with a message naming the command: `spawn --command` with a command not in `config.toml`, any `spawn --env`, `spawn --arg` with an arg not in `config.toml`, `spawn --system` with a system not in `config.toml`, `spawn --trust`, `roots add`, `launchers add`, `hive down` and `hive restart`. Wherever the sections above say such a call shows a prompt, do not run it: tell the user in one or two sentences what it does and give them the exact command to run by hand in a terminal. Other single `hive` commands, including `hive stop`, run directly.
- When the guard denies a call, do not look for workarounds; tell the user what was blocked and why.
- Never edit `config.toml` by hand; the commands keep it the single source of truth.
- Never suggest `hive down` or `hive restart` unless the user asks: they kill you and every worker.
- Report command output and errors back verbatim. Do not retry blindly.
