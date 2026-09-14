# Callout: the plan QA commit gate stops paying per plan folder

**Plan**: 00364
**Audience**: everyone

The `git commit` plan QA gate asked git what was staged once per plan folder
in the tree. On this repository that was 363 `git diff` subprocesses for one
commit; it is now one, because `GitFacts.staged_changes()` holds its answer
for the life of the context and `row-folder-bijection` only asks who is to
blame once it has a finding to attach the answer to. The cost grew with plan
count, so the projects that use the plan workflow most were paying most.
Verdicts are unchanged — a pre-existing mismatch still advises, one this
commit introduces still blocks.

Alongside it, three things an operator will notice. A `PLAN.md` that is not
valid UTF-8 no longer raises out of the commit gate; it reads as "no status",
which is what the surrounding code already promised. `settings.json` is now
written through a temp file and renamed into place, so an interrupted install
or upgrade can lose an update but can no longer leave a half-written file that
Claude Code cannot parse. And when `transport verify` finds the daemon down,
it says so instead of reporting the exit-code translation as broken — the two
failures look identical on the wire, and the operator was being sent to the
wrong subsystem.

The `echd-capture` helper changed in two visible ways. `--help` now prints the
usage header and stops, rather than trailing off into the script's own inline
rationale. Its last-resort capture directory, used only when neither
`ECHD_CAPTURE_DIR` nor `CLAUDE_PROJECT_DIR` is set, is now a fresh private
directory created by `mktemp -d` instead of a fixed name under `/tmp`: a fixed
name in a world-writable directory is a symlink-redirect target, since
`mkdir -p` follows one that already exists. Both other rungs of the precedence
chain are unchanged.

Finally, the `hooks-daemon` skill's `description` now lists `optimise` and
`bug-report`, which it always accepted but never advertised — a request to
tune the daemon's configuration previously matched nothing.
