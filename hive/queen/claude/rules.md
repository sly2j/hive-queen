## Workspace trust

- Trust is per Claude config dir: the launcher's `config_dir` decides the trust file.
- `hive spawn` exits 3 and prints `untrusted: ...` when Claude Code does not trust the directory. Tell the user the exact directory, the trust root and the trust file from the message (`trust_file=` in `hive list` shows the same file). Say that trusting enables that folder's `.claude/settings.json` allow rules, hooks and env.
- Then rerun the same spawn command with `--trust` added. It shows the user a confirmation prompt, which is their answer; do not ask again in chat. Never add `--trust` pre-emptively, before `hive spawn` has reported `untrusted:`.
- If `hive list` shows a `pane ... waiting=trust` record, tell the user which pane is waiting and that they must run `hive attach` to accept the dialog there.

## Rules

- The question tool is `AskUserQuestion`. Your tools are Bash, Monitor, Read, Grep, Glob, Edit, Write, NotebookEdit and AskUserQuestion; a guard hook denies every other tool.
- Bash and Monitor run only a single `hive ...` command: no `;`, `&`, `|`, backticks, `$(`, redirects or newlines. Path arguments may not use globs or brace expansion (`{a,b}`, `{1..3}`) or point under a `secrets`/`private` path. Put no options before the subcommand (`hive -- down` is blocked); only `hive --version`, `-h`, `--help` and `--node NAME` are allowed there.
- File tools work only inside your own directory, never under a `secrets`/`private` path. You cannot write `.claude/`, `.mcp.json`, `.claude.json` or this `CLAUDE.md`; `CLAUDE.local.md` is writable: put local additions there (hive never writes it). Glob and Grep patterns may not contain `..` or a path part that mixes `{` or `[` with `.`.
- Some calls show the user a confirmation prompt: `spawn --command` with a command not in `config.toml`, any `spawn --env`, `spawn --system` with a system not in `config.toml`, `spawn --trust`, `roots add`, `launchers add`, `hive down` and `hive restart`. One call that matches several gets a single prompt with all the reasons. Before such a call, tell the user in one or two sentences what you are about to run and why. Other single `hive` commands, including `hive stop`, run without a prompt.
- When the guard denies a call, or the user rejects a prompt, do not look for workarounds; tell the user what was blocked and why.
- Never edit `config.toml` by hand; the commands keep it the single source of truth.
- Never run `hive down` or `hive restart` unless the user asks: they kill you and every worker. Both show a confirmation prompt, which is the user's answer; do not ask again in chat.
- Report command output and errors back verbatim. Do not retry blindly.
