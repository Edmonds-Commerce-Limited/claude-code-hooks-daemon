# Release Notes — Pending Callouts

This directory holds **one short release-notes callout per plan**, written by
the plan that made the change, at the moment the plan closes. The release
folds every callout into `RELEASES/vX.Y.Z.md` and empties this directory.

It exists because the commit log cannot supply the sentence an operator
needs ("the upgrade resolves the host-a scenario, so the workaround can go"),
and because a plan must never wait for a release to say it — a plan is done
when its work is merged into main (`CLAUDE/core/PlanWorkflow.core.md`,
"Definition of done"). Writing the callout here IS the plan's last step.

## What belongs here

A callout for any merged change a **reader of the release notes** should
hear about in the author's own words: a new command or gate, a security fix
and what it closed, a behaviour an operator will notice, a workaround that
can be retired. Not every plan needs one — pure CI, test-only and internal
refactors usually do not, and the plan's last Success Criterion then says
"no release-bound consequences".

## What does NOT belong here

- Anything a user must **act on** after upgrading — that is a
  `../post-upgrade-tasks/` task, which has a schema for detection and action.
- Config-key or truth changes — `../config-changes/`, `../truth-changes/`.
- Changelog entries. `CHANGELOG.md` is generated from commits at release time.

## File naming

```
NN-kebab-case-slug.md
```

`NN` is a two-digit ordinal in arrival order. The slug says what the callout
is about without opening the file.

## File structure (mandatory schema)

```markdown
# Callout: [short human title]

**Plan**: NNNNN
**Audience**: operators | handler authors | client projects | everyone

One to three sentences, in the voice of the release notes: what changed,
what it means for the reader, and what (if anything) they can now stop doing.
```

## How the release handles this directory

At release time the release agent reads every callout, folds each into the
release notes under the audience-matching heading, moves the files with
`git mv` into the versioned upgrade directory beside `post-upgrade-tasks/`
so provenance survives, and leaves only this README behind. A callout still
here after the notes are written aborts the release (Plan 00360).
