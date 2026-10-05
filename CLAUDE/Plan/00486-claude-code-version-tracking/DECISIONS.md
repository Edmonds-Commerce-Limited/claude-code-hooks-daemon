# Plan 00486 decisions

Rulings in this file are marked by who made them. An agent ruling is the coordinator's
and can be overturned by the owner; it is not an owner decision.

**Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** D1, D2 and D3 are
confirmed (resolved). They are internal, already built and reversible. Not owner rulings.

## D1: The per-release record is a YAML map (agent ruling, coordinator)

`CLAUDE/development/claude-code-versions.yaml` maps each daemon release to the Claude Code
version it was built and tested against, the review date and the review report path. One
file, machine-readable, so Phase 2's drift check can read it. The RELEASES notes front
matter was the rejected alternative: it is spread over one file per release.

Versions are read through `contract_status.py`'s existing reader; no second reader is
added. Backfill covers only what git evidence establishes (the releases that first
contained each hooks-contract audit: v3.59.0, v3.63.0, v3.65.0). Everything else is
`unknown`, never a guess.

## D2: The review runs as RELEASING.md sub-step 1c (agent ruling, coordinator)

Added as sub-step 1c rather than a renumbered step, because tests and docs pin the
existing step numbers. The reviewer is the read-only
`.claude/agents/claude-code-changelog-reviewer.md` (Read, Glob, Grep, Write; no Edit or
Bash). The report lands in `untracked/release-artifacts/` and is linked from the YAML.

## D3: The backfill starts at the last audited version (agent ruling, coordinator)

Nothing in the repository records the Claude Code version v3.67.0 was tested against, so
the first review starts at `META.json`'s `last_audited_claude_code_version` (2.1.272) and
runs to 2.1.288.
