# Plan 00403: the design decisions, and what each one is defending against

Five decisions shape everything in this plan. Each is here rather than in
`PLAN.md` because each is reasoning a future reader needs to re-derive if they
are considering changing the thing it explains.

## Redaction is by construction, not by inspection

A denylist of "things that look sensitive" is the shape that fails. It is the
same mistake as judging a path by its text rather than by what it is, which
produced three shipped false positives in Plan 00401 — and here the failure
direction is worse, because a denylist that misses is silent and the cost is
permanent.

So the report is assembled from fields the generator controls. `ReportFields`
IS the boundary: there is no `hostname`, no `git_remote`, no config dump, no
log window and no transcript, and that ABSENCE is the guarantee. A field that
does not exist cannot arrive by being forgotten somewhere downstream.

The single place client content can enter is the free text the reporter types,
and that is covered by two different rules — see the next two sections.

## The minimal synthetic reproduction is the load-bearing rule

A reproduction authored against invented paths under `untracked/scratch/`
cannot leak, removes most of the remaining surface in one move, and
independently produces a better issue — a maintainer can run it.

A reproduction naming a client path is therefore REFUSED rather than scrubbed.
That is deliberate and differs from how the prose fields are treated: a repro
carrying a real path is not a report needing cleanup, it is a report written
the wrong way, and the fix is to write a synthetic one.

A bug that genuinely cannot be reproduced synthetically is still reportable.
The report says `CANNOT REPRODUCE` explicitly and carries no client data
instead — a weaker report, not an invalid one.

## Daemon paths are ours; client paths are not

Scrubbing keeps `.claude/hooks-daemon/…` and `src/claude_code_hooks_daemon/…`
intact, because those ARE the substance of a daemon defect report. It rewrites
the project root, `$HOME`, the git remote, the branch name and the hostname to
placeholders.

The asymmetry is the point: a scrubber that removed every path would remove the
report's content, and one that removed none would remove the client's privacy.

## Unverifiable claims become checkable artefacts

The generator cannot know whether the reporter really read the source, or
really thought about configuration. It CAN require the report to name which
config options were considered and why each is insufficient, and which
`file:line` was read — and it can check that the citation resolves in the
installed version.

That is a lower bound rather than a proof, and the module says so rather than
implying more: a resolving line proves the line exists, not that anybody
understood it. It is still the difference between a report from someone who
looked and one from someone who did not, and those need different answers.

It is the same move `MUST_EXCEED_COMMENT_SIZE_BECAUSE` and the remote-docs
provenance frontmatter already make in this project: turn an unverifiable claim
into an artefact a machine can check the SHAPE of.

## The older-version rule is mechanical

Installed versus latest; when older, diff the release notes between them for
the named subsystem. If it changed, refuse and say upgrade first. If it did
not, allow the report and record that finding IN it — so a maintainer can see
the check ran rather than assuming it did.

Two asymmetries are deliberate. Being AHEAD of the newest tag is fine: a
contributor on the default branch is not behind. And being unable to check is a
REFUSAL rather than a pass, because an unchecked install and a
checked-and-clean one must never render the same.

This is the owner's rule ("ensure that they are running the latest version...
but can report issues if on an older one and there is no changes to the
relevant system") reached mechanically instead of asserted.
