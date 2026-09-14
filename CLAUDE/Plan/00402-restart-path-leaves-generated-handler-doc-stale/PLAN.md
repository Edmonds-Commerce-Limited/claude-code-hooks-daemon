# Plan 00402: restart path leaves generated handler doc stale

**Status**: Not Started
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct
**Graduated from**: [Plan 00400](../Completed/00400-niggles-ledger-nine/PLAN.md) N6

## Overview

A daemon restart regenerates the `<hooksdaemon>` block inside the project
`CLAUDE.md`, but never regenerates `.claude/HOOKS-DAEMON.md`. The restart path
runs `cmd_start` → `DaemonController.initialise` → `ClaudeMdInjector.inject`,
and the auto-commit it produces is scoped by `git commit --only CLAUDE.md`.
`DocsGenerator` — the only writer of `.claude/HOOKS-DAEMON.md` — is reached
from exactly one place, `cmd_generate_docs`. So a handler added in-repo updates
one generated artefact and silently rots the other.

That rot was observed, not theorised. `.claude/HOOKS-DAEMON.md` sat dated
`2026-09-13` announcing "UserPromptSubmit (5 handlers)" while six were
registered; it omitted `daemon_upgrade_detector` (priority 58) entirely, a
handler [Plan 00395](../Completed/00395-running-daemon-detects-source-changed-underneath-it/PLAN.md)
had shipped. A documented protection surface understated what actually guards
the project, and many restarts went by without correcting it.

Nothing could have caught it. `tests/conftest.py` forbids tests from writing
that file, so no test asserts its freshness. The docs-QA staleness check
compares the embedded version marker against `__version__`, so a drift that
happens **within one version** — which is every in-repo handler addition — is
invisible by construction. `check_handler_reference.py` reads the file for a
single rule, `undocumented-blocking-handler`, and its own docstring calls that
"a floor, not a ceiling"; `daemon_upgrade_detector` is ADVISORY, so that rule
structurally could not see it.

## The constraint that rules out the obvious fix

"Regenerate it on restart too" is wrong, and this is the crux of the plan.

That file's `> Generated on YYYY-MM-DD (vX.Y.Z) by generate-docs` header is the
project's only durable record of **which daemon version the tracked assets were
deployed from**. It is parsed by `utils/deployed_version.py:46` and read by
`scripts/upgrade.sh:378` into `_TRACKED_VERSION` to derive the upgrade's FROM
side, with an explicit fallback warning at `scripts/upgrade.sh:386` when the
stamp is absent. Rewriting the header on every restart would stamp it with
today's date and the *running* version, destroying the FROM signal that upgrade
computation depends on.

So the work is: detect and repair **body** drift while preserving the marker.

[Plan 00336](../Completed/00336-upgrade-path-residual-findings/PLAN.md) Task 3.1
already recorded this exact asymmetry and fixed only the upgrade path
(`scripts/upgrade_version.sh:489`, `:1268`). The restart-path half was left, and
this plan is that half.

## Goals

- Content drift between `.claude/HOOKS-DAEMON.md` and the live handler registry
  is **detected** rather than silently tolerated.
- The `> Generated on … (vX.Y.Z)` marker keeps meaning "the version these
  tracked assets were deployed from" — no change makes it mean "last restart".
- A test fails when the tracked file's body diverges from freshly generated
  output, closing the by-construction blind spot above.

## Non-Goals

- Changing what `regenerate-docs` does. It already writes both artefacts
  correctly and is the supported repair path.
- Re-fixing the upgrade path — Plan 00336 did that.
- Widening `undocumented-blocking-handler` to advisory handlers; that rule is a
  deliberate floor and is not the right place for a freshness check.

## Owner ruling required before Phase 2

Three approaches, and the choice is the owner's because they trade differently
between noise, safety and where the failure surfaces:

1. **Detect-and-advise at SessionStart / restart** — compare the generated body
   (excluding the marker line) against the tracked file and advise when they
   differ. Never writes, so the marker is untouchable. Matches the precedent set
   by `deployed_artefact_drift` and by Plan 00386's "detect-and-advise, never
   self-update" ruling.
2. **Regenerate the body, preserve the marker verbatim** — restart rewrites
   content but carries the existing `Generated on` line through unchanged. Keeps
   the file always-correct, at the cost of a restart writing tracked files (and
   the auto-commit question that follows).
3. **A QA/CI check only** — a check that fails when the tracked body differs
   from freshly generated output. No runtime behaviour change at all, zero
   marker risk, and the failure lands where the handler was added rather than on
   whoever next restarts.

Option 3 is the smallest change that closes the blind spot, and options 1 and 3
compose. Recording no recommendation beyond that: the ruling is the owner's.

## Tasks

### Phase 1: Reproduce

- [ ] ⬜ **Task 1.1**: Write a RED test that fails when `.claude/HOOKS-DAEMON.md`
  body diverges from freshly generated output, comparing everything except
  the `> Generated on …` marker line. Respect `tests/conftest.py`'s
  prohibition on writing the tracked file — generate into a tmp path and
  compare.
- [ ] ⬜ **Task 1.2**: Assert the marker line itself is NOT rewritten by the
  comparison path, so the FROM-version signal cannot regress.

### Phase 2: Close the gap (shape depends on the ruling above)

- [ ] ⬜ **Task 2.1**: Implement the ruled option.
- [ ] ⬜ **Task 2.2**: Cover the preserved-marker invariant with a test that
  fails if a future change stamps the running version into the file.

### Phase 3: Documentation truth

- [ ] ⬜ **Task 3.1**: The false claim in `.claude/skills/hooks-daemon/regen-docs.md`
  and the `hooks-daemon` SKILL.md is corrected under Plan 00400 N6; confirm
  no other surface repeats it.

## Success Criteria

- [ ] A test fails against today's code when the tracked handler doc's body is
  stale relative to the live registry, and passes once regenerated.
- [ ] The `Generated on` marker still reports the deployed-from version after
  the change; `scripts/upgrade.sh` FROM-version derivation is unaffected.
- [ ] No documentation claims a restart refreshes both generated artefacts.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Graduated from Plan 00400 N6 with the evidence recorded there.
