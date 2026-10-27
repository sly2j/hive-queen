# Development

```sh
git clone https://github.com/sly2j/claude-rc-hive
cd claude-rc-hive
uv sync
uv run --frozen pytest -q
uv run hive --version
```

The tests need git. `tests/test_tmux.py` runs a throwaway tmux server on its own socket with a temporary `HOME`, and is skipped when tmux is not installed. Run `uv sync` after pulling, or `uv run hive --version` keeps reporting the version of the last sync.

Try changes against a live hive in a [test profile](test-profile.md) (`uv run hive --profile test ...`), which keeps your real hive's config and tmux server out of reach.

To update an installed copy after pulling or changing the repo:

```sh
uv tool upgrade hive         # or: uv tool install --reinstall .
```

## Layout

`hive/cli.py` only parses arguments and dispatches. The session lives in `lifecycle.py` (`up`, `down`, `restart`, `status`, `attach`, `reconcile`) over `tmux.py` (every tmux call) and `launch.py` (what a pane runs); `reconcile.py` holds the pure parts (desired panes, start/stop plan, target resolution) and `workers.py` the `list`, `spawn` and `stop` commands. `config.py` and `configedit.py` read, validate and edit `config.toml`; `lock.py`, `paths.py` and `util.py` are shared helpers. One module each: `activity.py` with `hooks/status_hook.py` (pane state), `sessions.py` (kept sessions), `trust.py`, `launchers.py` with `inspect.py`, `roots.py` with `dirs.py`, `nodes.py`, `service.py`, and `queen.py` with the packaged queen files under `queen/`. `drivers/` has one module per agent system (`claude.py`, `codex.py`): default command, required tokens, trust file, dialogs, hook and resume flags.

## Versioning

The version is in `VERSION`, scheme `MAJOR.MINOR`. A pre-commit hook bumps the minor on every commit on `main`, and does nothing on other branches; a release sets the major by hand and is tagged. Enable the hook once per clone:

```sh
git config core.hooksPath .githooks
```

The hook computes the new version from `HEAD:VERSION`, so re-running after an aborted commit does not bump twice. Feature branches: rebase on `main`, then squash-merge as one commit, so `main` stays linear and gets exactly one increment. `git commit --amend` on `main` bumps again; amend with `--no-verify`.
