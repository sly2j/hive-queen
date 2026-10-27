---
domain: process
summary: supervisor may squash-merge each feature to main and push after tests and test-hive validation; stops only for design forks and the final release/tag
affects: []
verified: 2026-10-27
source: user 2026-10-27 (supervisor session, AskUserQuestion)
supersedes:
---
Supervisor squash-merges each finished feature to main and pushes once the tests and the test-hive validation pass. It stops to ask only at a genuine design fork and at the final major release and tag.
Why: the user wants autonomous progress on a long multi-feature effort.
Rejected: asking before every merge or push.
