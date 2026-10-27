---
domain: process
summary: live checks use an isolated test profile with the fake worker, and production pane listings are recorded before and after each run
affects: [tests/data/fake_worker.py]
verified: 2026-10-27
source: user 2026-10-27
supersedes:
---
Hands-on validation runs through an isolated test profile with `tests/data/fake_worker.py` as the worker, and the production pane listing is recorded before and after every live run.
Why: this kept both production hives untouched across about 15 live checks, and the before/after listing proves it.
