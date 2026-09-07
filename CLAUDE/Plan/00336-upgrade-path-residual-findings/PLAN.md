# Plan 00336: upgrade path residual findings

**Status**: In Progress
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A client's v3.61.0 → v3.62.0 upgrade produced a six-defect field report. All
six are fixed and shipped (commits `b1217789`, `a9866261`). This plan carries
the residue: four findings that surfaced while fixing them, each deliberately
left out of that change because it is a design question rather than a defect
repair, and one of which the field report itself raised as an observation
rather than a defect.

Two of the four are behavioural and matter more than their "follow-up" framing
suggests. Item 2 in particular means the config-preservation baseline is
computed against the wrong side of the version boundary on the documented
upgrade path, so changed defaults may never reach users who had accepted the
previous ones — that is a silent, ongoing effect on every client, not a
one-release accident.

Items 1, 3 and 4 are smaller: an efficiency and structure question in the
upgrade orchestrator, a stale-guidance window immediately after upgrading, and
a documented bootstrap command that this project's own new handler denies.

## Goals

- Establish whether the config-preservation "old default" baseline is wrong on
  the Layer 1 path, and if so make the diff compare against the version being
  upgraded FROM.
- Decide and implement the shape of Layer 2's post-checkout recovery: keep the
  current full second pass, or resume at Step 7 with an explicit state
  handover.
- Close the window in which a project's resident agent guidance describes the
  pre-upgrade version.
- Remove the contradiction between the documented bootstrap fetch and
  `project_containment`.

## Non-Goals

- Re-fixing any of the six defects already shipped — they have tests and are
  verified live.
- Rewriting historical upgrade guides under `CLAUDE/UPGRADES/v3/`. Those record
  what a past upgrade looked like; editing them would falsify the record.
- Changing `settings.json` merge behaviour — that is Plan 00176's scope.

## Tasks

### Phase 1: The config-preservation baseline (highest value)

- [x] ✅ **Task 1.1**: Confirm the finding and pin it with a failing test.
  **Done.** `scripts/upgrade.sh` checks the target out and only then invokes
  Layer 2, never copying `.claude/hooks-daemon.yaml.example` beforehand, so
  Layer 2's Step 5 copies the NEW default under a comment claiming it is the
  old one. `tests/integration/test_upgrade_old_default_baseline.py` pins the
  contract: 7 of its 9 tests were RED before the fix.
- [x] ✅ **Task 1.2**: Establish the consequence empirically rather than by
  reasoning. **Done — measured, and it is real.** Driving `ConfigDiffer` and
  `ConfigMerger` directly with a default that changed between versions
  (`log_level` `INFO` → `WARNING`) and a user who simply accepted the old one:
  against the true old default the value is not a customisation and the merge
  yields `WARNING`; against the new default it is recorded as
  `custom_daemon_settings = {'log_level': 'INFO'}` and the merge yields
  `INFO`. A changed default does not reach a user who had accepted the
  previous one. Evidence in the journal.
- [x] ✅ **Task 1.3**: Fix it. **Done.** Layer 1 preserves the example config at
  a new Step 3c — alongside the existing `FROM_VERSION` capture, which already
  exists for exactly this deadline — and exports
  `HOOKS_DAEMON_OLD_DEFAULT_CONFIG`. Layer 2's Step 5 now calls a new
  `resolve_old_default_config()` in `install/config_preserve.sh`, which prefers
  the handover and otherwise falls back to the on-disk example, so BOTH entry
  points end up with a true old-version baseline and the direct-invocation path
  is unchanged. The copy is kept outside `DAEMON_DIR` because Layer 1's
  checkout is a `reset --hard` for a normal install and would discard it.
  Rejected the `git show <previous-ref>:...` alternative: on the Layer 1 path
  Layer 2 no longer knows the previous ref, so it would need the same handover
  anyway — one mechanism beats two.

### Phase 2: Layer 2 post-checkout recovery shape

- [ ] ⬜ **Task 2.1**: Decide between the shipped full second pass and a
  resume-at-Step-7 design. The state crossing the checkout boundary is
  small and known: `SNAPSHOT_ID`, `CONFIG_BACKUP`, `OLD_DEFAULT_CONFIG`,
  `CURRENT_VERSION` (`ROLLBACK_REF` is recomputable). The cost of resuming
  is restructuring Steps 1-6 into a skippable region in a 1200-line script
  that upgrades every client; the cost of not resuming is doing the work
  twice on a direct Layer 2 invocation.

- [x] ✅ **Task 2.2**: Rollback contract. **Resolved by not resuming** — the
  second pass runs only after Step 17, with the upgrade already successful and
  `UPGRADE_STARTED=false`, so no snapshot has to cross the boundary. Verified
  separately that `exec` does not fire the EXIT trap, so the re-exec cannot
  trigger a spurious rollback.

- [x] ✅ **Task 2.3**: Record the decision. **Done — KEEP the second pass.**
  The gap it leaves is narrower than it first appeared, because under Layer 1
  (checkout at line 440, Layer 2 invoked at 478) Layer 2 starts as a fresh
  process AFTER the checkout, so its script body AND its sourced
  `install/*.sh` libraries are all the new release. The "steps run from old
  code" problem is therefore confined to DIRECT Layer 2 invocation — the path
  the Defect 4 documentation fix now steers people away from — and the second
  pass already covers new steps there. A blanket re-source of the libraries
  after checkout was considered as a cheaper alternative and REJECTED:
  `gitignore.sh` and `rollback.sh` declare `readonly` variables, and
  re-assigning a readonly under `set -e` aborts the script.

- [x] ✅ **Task 2.4** (added): Boundary of what the first pass runs as old
  code. Only the SHELL is stale. Step 7 rebuilds the venv from the new
  checkout, so every `"$VENV_PYTHON" -m claude_code_hooks_daemon...` call from
  Step 8 onward already executes the new release's Python. A fix in
  `config_differ.py` reaches the upgrade that delivers it; a fix in
  `config_preserve.sh` does not.

- [ ] ⬜ **Task 2.5** (added, and the largest finding in this phase): **On a
  standard Layer 1 tag upgrade, config preservation and merging never run at
  all.** Layer 1 checks out first, so Layer 2's Step 2 finds
  `ROLLBACK_REF == TARGET_VERSION`, takes the idempotent fast path, and
  `exit 0`s at line 418. `preserve_config_for_upgrade` is called from exactly
  one place — line 861, Step 10 — which the fast path never reaches. Confirmed
  by grep: Layer 1 contains no config-merge call of its own, and the fast path
  (269-418) contains none either, though it IS otherwise comprehensive (venv,
  hooks, slash commands, skills, plan workflow, core docs, ccy, relay, restart,
  post-install checks).

  Judge the impact before acting: this is staleness, not data loss. The user's
  config is left untouched, and the Pydantic schema supplies defaults for keys
  that are absent, so behaviour still follows the new defaults at runtime — the
  config FILE simply never gains the new entries. The config-optimisation
  review may well be the intended mechanism for adopting new handlers. The
  question for the owner is whether the fast path skipping Step 10 is deliberate
  or an accident of where the early `exit 0` landed.

### Phase 3: Stale resident guidance after an upgrade

- [ ] ⬜ **Task 3.1**: The `<hooksdaemon>` block in a project's `CLAUDE.md` and
  `.claude/HOOKS-DAEMON.md` are not regenerated by the upgrade. Immediately
  after upgrading, agents are denied by rules their own guidance does not
  document — v3.62.0 shipped an enabled-by-default deny handler, so this
  window is not hypothetical.
- [ ] ⬜ **Task 3.2**: Run `regenerate-docs` as part of the upgrade, or prompt
  for it. Check the interaction with Plan 00329 (post-upgrade report
  bloat) before adding output to the upgrade's closing sequence.

### Phase 4: The bootstrap fetch conflicts with `project_containment`

- [ ] ⬜ **Task 4.1**: `README.md` and `CLAUDE/LLM-UPDATE.md` instruct
  `curl -fsSL ... -o /tmp/upgrade.sh` and `-o /tmp/LLM-UPDATE.md`.
  `project_containment` explicitly covers `curl -o`, so an agent in an
  installed project is denied when following the documented AI-assisted
  update flow.
- [ ] ⬜ **Task 4.2**: Resolve it in the direction that keeps the security
  property. The fetch-review-run pattern exists so the operator reads the
  script before executing it; moving the destination inside the repository
  preserves that and satisfies the handler, but the install case may have
  no repository yet. Handle the two cases separately rather than with one
  compromise.

## Success Criteria

- [ ] The config-preservation diff baseline is the version being upgraded FROM
  on both entry points, pinned by a test that fails against today's code.
- [ ] Layer 2's post-checkout recovery shape is decided, implemented and
  documented, with the rollback contract verified either way.
- [ ] A project's generated agent guidance matches the installed version
  immediately after an upgrade completes.
- [ ] No shipped document instructs a command that this project's own handlers
  deny.
- [ ] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00336-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: the six defects fixed in `b1217789`; re-exec argument fix in
  `a9866261`. This plan is the residue of that work.
- Dedupe scout checked 44 live plans and found none covering these four items.
  Plan 00291 is closest by source (also from a client upgrade failure) but its
  stated scope does not encompass them; Plan 00176 covers `settings.json`
  rather than `hooks-daemon.yaml`; Plan 00329 bounds post-upgrade report size
  rather than ensuring the guidance block is regenerated.
