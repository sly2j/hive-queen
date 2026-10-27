# Workspace trust

This page is about Claude Code's folder trust. Codex keeps its own trust record in its `config.toml`, and `hive spawn --trust` seeds that one for a Codex type; see [Codex: Config dir and trust](systems/codex.md#config-dir-and-trust).

Claude Code stores the answer to its "trust this folder?" dialog in a trust file as `projects["<root>"].hasTrustDialogAccepted = true`. `<root>` is the trust root: the git repo root of the directory (`git rev-parse --show-toplevel`), else the directory itself. hive checks only that exact key. It ignores trust Claude Code would inherit from a trusted parent folder or, in a linked worktree, from the main checkout, so it may ask when Claude would not.

The trust file is `<config_dir>/.claude.json` when the agent type (or `[queen]`) has `config_dir`. Without `config_dir`, it is `$CLAUDE_CONFIG_DIR/.claude.json` if hive's own environment has `CLAUDE_CONFIG_DIR`, else `~/.claude.json`. With `spawn --launcher`, the chosen launcher's `config_dir` is used. So the systemd service, a plain shell and the queen can each resolve a different trust file and disagree on whether a directory is trusted. Panes do not inherit hive's `CLAUDE_CONFIG_DIR` (see [Panes and environment](concepts.md#panes-and-environment)), so a launch command that does not set it uses `~/.claude.json` even when hive checked another file. Set `config_dir` to pin it.

hive never seeds trust silently. `hive spawn` checks the trust root (in the chosen launcher's `config_dir`, its `.claude.json`) before editing the config; if it is untrusted it prints `untrusted: <dir> (trust root <root>, trust file <file>); rerun with --trust after the user confirms` to stderr and exits 3 without changes. Rerun with `--trust` once you have confirmed: hive sets only that one key, under Claude Code's lock on the file (it refuses a trust file that is not valid JSON), prints `trusted <root> in <file>`, and proceeds.

`hive up` and `hive reconcile` (also `--dry-run`) warn `untrusted <name> <root>` for each pane they would start in an untrusted root, and still start it. The pane shows the dialog, which you accept via `hive attach`. `hive list` marks such a pane `waiting=trust`.
