# Development

```sh
git clone https://github.com/sly2j/claude-rc-hive
cd claude-rc-hive
uv sync
uv run --frozen pytest -q
uv run hive --version
```

The tests need git. `tests/test_tmux.py` runs a throwaway tmux server on its own socket with a temporary `HOME`, and is skipped when tmux is not installed. Run `uv sync` after pulling, or `uv run hive --version` keeps reporting the version of the last sync.

To update an installed copy after pulling or changing the repo:

```sh
uv tool upgrade hive         # or: uv tool install --reinstall .
```

## Versioning

The version is in `VERSION`, scheme `1.x`. A pre-commit hook bumps it on every commit on `main`, and does nothing on other branches; the first commit is `1.0`. Enable the hook once per clone:

```sh
git config core.hooksPath .githooks
```

The hook computes the new version from `HEAD:VERSION`, so re-running after an aborted commit does not bump twice. Feature branches: rebase on `main`, then squash-merge as one commit, so `main` stays linear and gets exactly one increment. `git commit --amend` on `main` bumps again; amend with `--no-verify`.
