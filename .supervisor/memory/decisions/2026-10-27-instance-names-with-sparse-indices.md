---
domain: code
summary: workers are named <type>-<machine>-<N>, queen hive-queen-<machine>; N is derived 1..count unless a sparse indices list is stored; legacy panes adopted in place
affects: [hive/reconcile.py, hive/workers.py, hive/config.py, hive/queen/queen.md]
verified: 2026-10-27
source: .supervisor/archive/working/plans/plan-hive-queen-2.0.md (D6, Log 2026-10-27); supersedes the naming entry's "never stored" clause
supersedes: .supervisor/archive/memory/decisions/2026-10-22-instance-naming-and-queen-rename.md
---
Worker instance, window and RC session names are `<type>-<machine>-<N>`; a launcher-chosen type is `<dir>-<launcher>`. Machine is the `prefix` key (default short hostname, validated `[A-Za-z0-9._-]+`); window is `<type>-<machine>`; tmux session `<prefix>-agents`. The queen is `hive-queen-<machine>`; `hive-queen` is a reserved type name like `queen`.
N is derived 1..count while contiguous. Removing one worker stores an `indices` list, exclusive with `count`, so the other workers keep their names and RC sessions; contiguous lists collapse back to `count`. `stop` resolves a type name first, so `--index N` is the unambiguous form.
Why: type and launcher first makes wrong-launcher workers visible; a worker can be removed without renaming the rest.
Rejected: tombstones or a pane-id map; renumbering survivors (renames running RC sessions).
Legacy panes (`<prefix>-queen`, `<prefix>-<type>-<N>`) are adopted without restart when the canonical name is desired; legacy panes of removed types stay unmanaged.
