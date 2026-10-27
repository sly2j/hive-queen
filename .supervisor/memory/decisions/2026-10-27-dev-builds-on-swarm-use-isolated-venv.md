---
domain: process
summary: dev builds on swarm run from an isolated venv and never replace the installed hive tool
affects: []
verified: 2026-10-27
source: supervisor default 2026-10-27 (user did not object; overturnable)
supersedes:
---
A development build on swarm lives in its own venv; the installed `hive` tool there is never replaced or reinstalled for testing.
Why: swarm runs a production hive that must stay untouched.
