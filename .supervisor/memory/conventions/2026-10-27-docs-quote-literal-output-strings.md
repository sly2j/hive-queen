---
domain: writing
summary: docs quote the literal string in backticks when describing what a command prints or an error says
affects: [docs/, README.md]
verified: 2026-10-27
source: user 2026-10-27
supersedes:
---
When a docs page describes what a command prints or what an error says, it quotes the literal string in backticks; output is never paraphrased.
Why: readers search for and compare against the exact text they see.
Rejected: paraphrased descriptions of output, which drift from the real strings.
