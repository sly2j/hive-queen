---
domain: process
summary: VERSION keeps the 1.x-style per-commit bump; a major release sets the major version, and releases are tagged
affects: [VERSION]
verified: 2026-10-27
source: supervisor default 2026-10-27 (user did not object; overturnable)
supersedes:
---
The per-commit minor bump scheme in VERSION stays. A major release sets the new major version and gets a git tag; tagging releases starts with it.
Why: smallest change to the existing workflow while giving users a stable reference.
Rejected: switching to date or semver-per-change schemes.
