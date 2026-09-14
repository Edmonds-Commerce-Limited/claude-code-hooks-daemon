# Callout: four guards corrected by the release review

**Plan**: 00407
**Audience**: everyone

The code-review gate for this release found four defects that reach users. All
four are fixed here.

**A merge described in a commit message is no longer a merge.**
`merge_to_main_approval` blanked quoted literals but not a heredoc BODY, so a
`git merge` named in prose inside one was read as a real merge. With
`worktree.merge_to_main_requires_human_approval` on, any commit whose message
described a merge was denied, naming a remediation about a command nobody ran —
and the shape that triggered it includes the `git commit -m "$(cat <<'EOF' … EOF)"` idiom. Only projects that opted the key on were affected, and for them
it was unavoidable.

**A `cd` described in prose is no longer a directory change.** The same class,
in `daemon_location_guard`: text inside a quoted heredoc or a single-quoted
string is data, and naming the daemon directory there is not entering it. This
was found by the daemon denying an agent that was writing a report ABOUT the
first defect.

**A drift detector no longer goes silently blind.** `deployed_artefact_drift`
hardcoded `CLAUDE/Plan`. A project with a different configured plan directory
got no report at all — not an error, just silence — from a handler whose whole
purpose is to make a repairable problem visible. It now reads the configured
directory and names it in the report, so the path you are told to fix is the
path you actually have.

**Security fix: the upstream filing gate covers `gh`'s default repo
resolution.** `issue_filing_gate` recognised `--repo` and `GH_REPO`, but `gh`
falls back to the git remotes of the working directory when neither is given —
and that is its DEFAULT. Every client install carries a clone of this
repository under `.claude/hooks-daemon/`, so a bare `gh issue create` typed
with the shell inside that clone filed a hand-written, unverified body against
a PUBLIC tracker while the gate stood by. That is the one failure the gate
exists to prevent and it cannot be retracted after the fact.

The working directory is consulted only when nothing else names a repository,
matching `gh`'s own precedence, and a directory git cannot resolve answers "not
ours" — gating on an unresolvable path would deny your ordinary filing on your
own tracker, which is the false positive that gets a guard switched off.
