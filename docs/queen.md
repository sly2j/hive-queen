# Queen

The queen is a persistent Claude session, window and Remote Control session `hive-queen-<machine>`, always started first. It runs the `hive` commands for you: ask it for "one more X" or "one less X" and it edits `config.toml` through `hive spawn` and `hive stop`, which then reconcile the session. Config stays the single source of truth; the queen is never stopped by reconcile, only by `hive down`.

With the default `[queen] command` the queen runs with Remote Control on. A custom `[queen] command` without `--remote-control` gets only a warning when the queen starts.

Its directory is `${XDG_CONFIG_HOME:-~/.config}/hive/queen`. hive manages `CLAUDE.md`, `.claude/settings.json` and `.claude/hooks/guard.py` there and rewrites them when they are missing or differ from the packaged copy. This happens only when the queen pane starts: on a fresh `hive up`, or when reconcile finds the queen missing. After upgrading hive, run `hive restart` to re-sync them. Put your own additions in `CLAUDE.local.md`; hive never writes it.

For a spawn with a custom launcher command and no known `config_dir`, the queen tries to infer the launcher's config dir with `hive inspect-launcher` (it never runs the launcher). When it finds one, it tells you the evidence and asks you to confirm before it passes `--config-dir`; with no evidence it assumes the default trust file.

## Queen security model

The queen runs with `--permission-mode auto` by default, so its limits come from the flags hive adds to its command and the files hive manages in its directory:

- The queen's tools are limited to Bash, Monitor, Read, Grep, Glob, Edit, Write, NotebookEdit and AskUserQuestion (for its launcher choice dialogue). hive appends `--tools Bash,Monitor,Read,Grep,Glob,Edit,Write,NotebookEdit,AskUserQuestion --strict-mcp-config` to the queen command unless the queen's command or its `args` already contain `--tools` or `--strict-mcp-config`, and the guard hook denies every other tool (WebFetch, WebSearch, Agent, MCP tools) with `guard: tool '<name>' is not available to the queen`.
- `.claude/settings.json` allows `Bash(hive:*)` and denies the Read tool on `~/.ssh`, `~/.claude`, `~/.claude.json`, `~/.gnupg`, `~/.aws`, `.env` files and `secrets`/`private` paths.
- A PreToolUse guard hook (`.claude/hooks/guard.py`, matcher `*`) checks every tool call. If the hook fails (it crashes), the call is blocked; this needs Claude Code >= 2.1.295, and older versions let the call through.
- Shell tools (Bash, Monitor): only a single `hive` command is allowed, with no `;`, `&`, `|`, backticks, `$(`, redirects or newlines; path arguments may not use globs or brace expansion or point under a `secrets`/`private` path. No options before the subcommand (`hive -- down` is blocked); only `hive --version`, `-h` and `--help` are allowed there. Anything else is blocked.
- These `hive` commands get a confirmation prompt that names what they do (when one call matches several, the reasons are combined into one prompt):
  - `hive spawn --command CMD`, unless CMD equals a command already in `config.toml` (`[defaults] command` or an `[[agents]] command`). It also prompts when `config.toml` cannot be read. `--command=CMD` and abbreviations such as `--comm` count too.
  - `hive spawn --arg ARG`, unless ARG is an arg string from `config.toml` (`[defaults]`, `[queen]` or `[[agents]]` `args`), like `--command`.
  - `hive spawn` with any `--env`, since a variable such as `BASH_ENV` could get around the command check.
  - `hive spawn ... --trust`.
  - `hive roots add PATH`.
  - `hive launchers add`, since a registered launcher then runs through `spawn --launcher` without a `--command` prompt.
  - `hive down` and `hive restart`, which stop the whole hive, the queen included.
- A blocked call stays blocked; the prompt never overrides it.
- File tools: only paths inside the queen's directory, never under a `secrets`/`private` path. Glob and Grep patterns may not contain `..` or a path part that mixes `{` or `[` with `.`. No writes to its `.claude/`, `.mcp.json`, `.claude.json` or `CLAUDE.md`; `CLAUDE.local.md` is writable.

What this does not cover: every other single `hive` command runs without a prompt, including `hive stop`. The workers the queen spawns are ordinary panes and get none of these restrictions.
