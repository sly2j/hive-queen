---
domain: process
summary: repo and Python package are named hive-queen; installed command stays hive; docs carry an upgrade note for existing installs
affects: [pyproject.toml, README.md, hive/]
verified: 2026-10-27
source: user 2026-10-27 (supervisor session, AskUserQuestion)
supersedes:
---
The GitHub repo and the Python package/dist are `hive-queen` (`uv tool install hive-queen`); the installed command stays `hive`. Docs include an upgrade note for existing `hive` installs.
Why: the name says what the project is while keeping the short command and existing muscle memory.
