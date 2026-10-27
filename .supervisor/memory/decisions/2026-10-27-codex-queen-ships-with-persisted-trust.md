---
domain: process
summary: Codex queen ships; Codex may persist folder and hook trust in ~/.codex/config.toml after one Trust all, and re-trust on hash change is accepted
affects: [hive/]
verified: 2026-10-27
source: user 2026-10-27 (supervisor session, AskUserQuestion "Allow it; ship the Codex queen")
supersedes:
---
The Codex queen ships. Codex may write the queen's folder trust (`[projects."<queen dir>"]`) and hook trust (`[hooks.state."<key>"] trusted_hash`) to the user's ~/.codex/config.toml after one interactive "Trust all" in the queen pane. Re-trusting is an accepted upgrade step whenever hive changes the guard files' hash.
Why: the queen's guard hooks need Codex trust, which Codex stores only in the user's config; the user accepts that write.
Rejected: shipping no Codex queen, or bypassing hook trust, which forces embedded mode.
