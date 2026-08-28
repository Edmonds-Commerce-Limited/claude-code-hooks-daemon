---
paths:
  - "untracked/hooks-daemon-*"
  - "untracked/hooks-daemon-*/**"
description: How an incoming report becomes tracked source — sanitise before committing, this repo is public
---

# Importing a report from `untracked/hooks-daemon-*`

You touched an incoming report. This repository is PUBLIC: read the report in
full and strip reporter-specific identifiers BEFORE committing it anywhere,
then give it one of its two fates — delete once acted on, or track it in the
relevant plan folder. The canonical rule is root `CLAUDE.md`'s "Report
Handling" section; the identifier-replacement conventions are in
[CLAUDE/development/DOC-CONVENTIONS.md](../../CLAUDE/development/DOC-CONVENTIONS.md),
and plan-folder promotion is
[CLAUDE/DocumentationStrategy.md](../../CLAUDE/DocumentationStrategy.md) R8.
When filing a plan from a report, carry the report's nuance: an approach the
report argues against becomes a Non-Goal with its reason, not an omission.
