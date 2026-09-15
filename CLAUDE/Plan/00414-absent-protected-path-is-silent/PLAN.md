# Plan 00414: absent protected path is silent

**Status**: Not Started
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

`secret_file_hygiene_checker` reports, at SessionStart, on every configured
protected path **that exists on disk** — not gitignored, git-tracked,
group/world-readable. A path that does not exist produces nothing.

That is a reasonable rule for a hygiene checker and a poor one for the reader,
because the two states it collapses are opposites. "Your word list is fine" and
"you have no word list, so that guard has been inert since you cloned" are
reported identically: by silence. The daemon's documented behaviour for a
missing list is to stand the source down quietly, which is correct at runtime —
a missing file must not break a session — and unhelpful exactly once, on the
first run, to the one person who does not yet know the file is expected.

This was found as N3 of ledger [00413](../Completed/00413-niggles-ledger-thirteen/PLAN.md)
when a new collaborator cloned the repository. `.claude/block-words.secret` and
its `.example` are both gitignored — deliberately, and `.gitignore:215-220`
gives the reason: the rule ships before any such file exists so that a broad
`git add` can never catch one. So the collaborator got a working daemon with
`sensitive_content`'s word-list source permanently inert, and nothing anywhere
said so.

**The fix is NOT to track the example.** That was the first idea and it is
wrong: it would weaken a deliberate defence-in-depth rule in order to fix a
reporting gap. The reporting gap is the thing to fix.

## Goals

- A configured protected path that is ABSENT is distinguishable, at
  SessionStart, from one that is present and healthy.

- The distinction is drawn without ever opening the file, reading its contents,
  or naming anything from inside it — the existing handler's metadata-only
  contract is not negotiable and this must not erode it.

- Silence continues to mean "checked, nothing wrong", so the advisory stays
  worth reading. A handler that speaks every session about a state the owner
  has deliberately chosen becomes noise, and noise is skimmed.

## Non-Goals

- **Blocking.** This is an advisory and stays one. A missing word list must
  never stop a session; the whole point of standing the source down silently at
  runtime is that the daemon keeps working.

- **Tracking `*.secret.example`.** See above — the ignore rule is deliberate,
  documented, and load-bearing.

- **Changing what `sensitive_content` DOES with a missing list.** Standing the
  source down is correct. This plan is about whether anyone is told.

## Open questions

These need settling before implementation, and they are genuinely open:

- **Is "absent" always worth reporting, or only when it is unexpected?** A
  project that never configured a word list has no gap; one that ships
  `block-words.secret` in its config and lacks the file does. The second is a
  real finding and the first is noise, and telling them apart may need an
  explicit declaration rather than inference.

- **Once per checkout, or every session?** A one-shot notice is easy to miss
  and easy to ignore; a per-session one is the noise failure above. The
  existing `deployed_artefact_drift` and `reference_repo_sweep` handlers have
  each already answered a version of this question — their answers should be
  read before a third one is invented.

## Tasks

- [ ] ⬜ **Task 1.1**: Settle the two open questions above with the owner.

- [ ] ⬜ **Task 1.2**: Read how `deployed_artefact_drift` and
  `reference_repo_sweep` decide when to speak, and reuse rather than reinvent.

- [ ] ⬜ **Task 1.3**: Failing test first: a configured-but-absent protected
  path produces a finding; a configured-and-healthy one still produces silence.

- [ ] ⬜ **Task 1.4**: Implement, keeping the metadata-only contract — assert in
  a test that no code path opens a protected file.

## Success Criteria

- [ ] ⬜ A fresh clone whose config names a word list it does not have is told
  so, once, in terms that say which guard is inert as a result.

- [ ] ⬜ A checkout with nothing missing produces exactly the same output as
  today.

- [ ] ⬜ No protected file's contents are read on any path, proven by test.

## Delivery & Milestones

- Graduated from ledger [00413](../Completed/00413-niggles-ledger-thirteen/PLAN.md) N3,
  which was filed with the wrong fix (track the `.example`) and re-scoped once
  `.gitignore`'s own comment showed the exclusion was deliberate.
