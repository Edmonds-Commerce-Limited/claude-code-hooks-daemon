# Callout: unattended sessions, and scoped QA scans

**Plan**: 00413
**Audience**: operators

`ask_user_question_blocker` gains `mode: unattended`. Claude Code's own
mechanisms for "nobody is watching" are launcher flags, and they cannot reach a
cron job firing into a live interactive session — so a session that is
*sometimes* unattended had no way to say so. With the mode set, a question that
would have waited forever for an answer is refused, and the agent is told to
choose the option it would have recommended and continue.

Separately, `check_sensitive_content.py --path <dir>` no longer overwrites the
repository-wide QA artefact with the verdict for whatever it scanned. A scoped
run answering "is this directory clean" was publishing its answer as though it
were "is this repository clean", and that artefact is what the QA suite hands to
an agent to read. A plain test run could leave it reading `passed: false`
against a path under `/tmp` while the repository itself was clean.
