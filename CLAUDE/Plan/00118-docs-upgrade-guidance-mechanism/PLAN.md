# Plan 00118: Truth-Changes — Project Doc Reconciliation on Upgrade

**Status**: Not Started
**Created**: 2026-06-04
**Owner**: Claude (Opus)
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**Type**: Feature (small)

> **Design history**: An earlier draft of this plan (preserved in
> `archive/design1/`) proposed a much heavier mechanism — a
> git-config docs-synced marker, staleness detection, `detect:` shell probes,
> supersede/severity metadata, a QA validator, and a SessionStart push advisory.
> The user (correctly) called this over-engineered. **This PLAN is the
> deliberately simplified version.** The key realisation: the upgrade flow
> already knows the version range it crossed (`from_version`/`to_version` in the
> `UPGRADE_METADATA` block), so no marker, no staleness detection, and no
> SessionStart push are needed. SessionStart is also being reframed as
> human-only (issue #32), which independently rules it out as a delivery channel.

## Overview

When the daemon is upgraded, some statements that were **true** about how to work
in a project may become **false**, replaced by a **new truth** (or simply
retired). A project's own docs (`CLAUDE/`, `docs/`, `README`, `AGENTS.md`) often
still assert the old truth, and nothing reconciles them.

The mechanism is a simple per-version **truth-changes list** — essentially a
`was → now` table:

| was true                                                        | now true                                                                                                         |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Find the next plan number by scanning the `CLAUDE/Plan/` folder | Get it from `git config --local hooksdaemon.latestPlanNumber` (+1); the daemon updates it when a plan is created |
| `<some retired concept>`                                        | *(empty — no replacement; remove all reference to it)*                                                           |

At upgrade time the project LLM is handed the truth-changes for the version range
it crossed and instructed to **scan the project's own docs for each "was"
statement and update it to the "now" statement — or remove all reference when
there is no replacement.** That is the entire concept.

This reuses the existing `CLAUDE/UPGRADES/` clone-on-disk convention (shipped
downstream for free, refreshed on every upgrade) and the existing upgrade-skill
flow (`upgrade.md`) as the delivery channel. The only genuinely new things are a
trivial data format, one upgrade-flow step, and a small re-discovery CLI command.

## Goals

- A dead-simple per-version **truth-changes** data file: a list of `{was, now}`
  entries, where an empty `now` means "remove all reference, no replacement".
- **Delivery through the existing upgrade flow**: `upgrade.md` gains a step that
  feeds the project LLM the truth-changes for the `(from, to]` range (taken from
  `UPGRADE_METADATA`) and tells it to reconcile the project's own docs.
- A small **re-discovery CLI** (`check-truth-changes --from X --to Y`) so an LLM
  can re-fetch the list any time, not only mid-upgrade.
- The **plan-number truth-change** authored as the first real entry.
- The stateless companion fix: `plan_number_helper.get_claude_md()` returns the
  *current* truth (it returns `None` today) so the daemon's own injected guidance
  and the truth-change tell the same story.
- Light **governance**: a release that changes a documented truth adds a
  truth-changes entry (one extra line in the existing release move-step).

## Non-Goals (explicitly cut as over-engineering)

- ❌ No git-config docs-synced marker — the upgrade flow already knows from→to.
- ❌ No staleness detection / SessionStart advisory / any push channel (the LLM
  is already in the upgrade flow; SessionStart is human-only per issue #32).
- ❌ No `detect:` shell probes — the LLM semantically searches its docs for the
  natural-language `was` statement.
- ❌ No `supersedes`/`severity`/`idempotent`/`targets` metadata, no schema
  validator, no skill subcommand, no `Handler.get_doc_upgrade_tasks()` hook.
- ❌ No mass back-fill — author only the plan-number entry now; future
  truth-changing releases add their own entries.

## Context & Background

- The upgrade entrypoint `scripts/upgrade.sh` emits an `UPGRADE_METADATA` block
  containing `from_version` and `to_version`; the `upgrade.md` skill already
  instructs the LLM to parse it and commit. That is the natural place to add the
  reconciliation step — the LLM is already there and already knows the range.
- `CLAUDE/UPGRADES/` is physically present downstream inside the cloned
  `.claude/hooks-daemon/`, refreshed to the target tag on every upgrade — exactly
  how `config-migrations` ships its per-version YAML manifests. Truth-changes
  files ship the same way; no new mechanism.
- `config_migrations.py` + `check-config-migrations` is the proven version-range
  loader to clone for the re-discovery CLI.
- `plan_number_helper.get_claude_md()` returns `None` today (the motivating gap).

## The data format

`CLAUDE/UPGRADES/truth-changes/v{X.Y.Z}.yaml` — one file per truth-changing
release (mirrors `config-changes/v{X.Y.Z}.yaml`):

```yaml
version: 3.12.0
truth_changes:
  - was: >
      Find the next plan number by scanning the CLAUDE/Plan/ folder for the
      highest NNNNN- prefix.
    now: >
      Get the next plan number from `git config --local hooksdaemon.latestPlanNumber`
      (+1). The daemon updates this counter automatically when a plan is created;
      fall back to scanning CLAUDE/Plan/ only if the key is unset.
  - was: "<an example retired concept the docs should no longer mention>"
    now: ~          # null/empty => remove all reference; there is no replacement
```

`was` is a natural-language statement the LLM matches **semantically** against the
project's docs (not a regex). `now` is the replacement, or null/empty to mean
"delete the guidance". That is the whole schema — two keys.

## Tasks

### Phase 1: Format, first entry, current-truth fix

- [x] ✅ **Task 1.1**: Define the truth-changes format + staging convention
  - [x] ✅ Document the `{version, truth_changes:[{was, now}]}` schema and the
    empty-`now`-means-remove rule (`CLAUDE/UPGRADES/truth-changes/README.md`)
  - [x] ✅ Create `CLAUDE/UPGRADES/UNRELEASED/truth-changes/` staging dir (+ README)
- [x] ✅ **Task 1.2**: Author the plan-number truth-change (proof entry)
  - [x] ✅ Wrote the **v3.16.0** entry — corrected from the PLAN's `3.12.0`
    placeholder: the git counter (Plan 00112) actually shipped in v3.16.0 per
    `RELEASES/v3.16.0.md`. Staged at `UNRELEASED/truth-changes/v3.16.0.yaml`.
- [x] ✅ **Task 1.3**: Fix `plan_number_helper.get_claude_md()` (TDD)
  - [x] ✅ Failing test: returns markdown stating the git-counter is authoritative
    (folder-scan only as unset-bootstrap)
  - [x] ✅ Implemented; renders in the `<hooksdaemon>` block (verified via
    `generate-docs` → CLAUDE.md)
- [x] ✅ **Task 1.4**: QA + daemon restart verification (13/13 PASSED, RUNNING)

### Phase 2: Delivery via the upgrade flow

- [ ] ⬜ **Task 2.1**: Add the reconciliation step to `upgrade.md`
  - [ ] ⬜ After parsing `UPGRADE_METADATA`, the LLM loads truth-changes for every
    version in `(from_version, to_version]` from the cloned
    `CLAUDE/UPGRADES/truth-changes/`
  - [ ] ⬜ For each `{was, now}`: semantically scan the project's own docs
    (`CLAUDE/`, `docs/`, `README*`, `AGENTS*` — never `.claude/hooks-daemon/`
    internals). Where the `was` truth appears: update it to `now`, or remove
    all reference when `now` is empty. Minimal edits; commit with a clear
    message.
  - [ ] ⬜ Idempotent by construction: if a doc no longer asserts `was`, nothing
    to do. A second upgrade-reconcile is a no-op.
- [ ] ⬜ **Task 2.2**: Dogfooding/acceptance — verify the step is present in the
  deployed skill and that `deploy_skills()` refresh carries the updated
  `upgrade.md`

### Phase 3: Re-discovery CLI (small)

- [x] ✅ **Task 3.1**: `check-truth-changes` command (TDD)
  - [x] ✅ Tests for `--from/--to/--format text|json`, exit codes 0 (no changes) /
    1 (changes present) / 2 (error) — `tests/unit/install/test_truth_changes.py`
  - [x] ✅ Implemented `install/truth_changes.py` by cloning the
    `config_migrations.py` range loader (minus user-config compare); prints the
    aggregated `was → now` list. CLI `cmd_check_truth_changes` registered.
  - [x] ✅ `CliAcceptanceTest`: plan-number entry surfaces for `--from 3.11.0 --to 3.17.0` (verified live; exit 1)
- [x] ✅ **Task 3.2**: QA + daemon restart verification (RUNNING)

### Phase 4: Governance (light)

- [ ] ⬜ **Task 4.1**: RELEASING.md integration
  - [ ] ⬜ Extend the existing Step 6 move to also move
    `UNRELEASED/truth-changes/` into `CLAUDE/UPGRADES/truth-changes/`
  - [ ] ⬜ Add one Step 7 checklist line: "did this release change a documented
    truth? add a truth-changes entry"
- [ ] ⬜ **Task 4.2**: Final QA, daemon restart, changelog + HOOKS-DAEMON.md
  regeneration

## Dependencies

- **Reuses**: the `CLAUDE/UPGRADES/` clone convention, `config_migrations.py`
  range loader, the `upgrade.md` skill flow + `UPGRADE_METADATA`, Plan 00112's
  git counter (the subject of the first truth-change).
- **Related**: issue #32 (reframe SessionStart as human-only) — reinforces that
  delivery is via the upgrade flow, not a session message.
- **Blocks**: none.

## Technical Decisions

### Decision: No marker, no push — deliver inside the upgrade flow

**Context**: The original design added a persisted docs-synced marker + a
SessionStart advisory to detect staleness and nudge. **Decision**: drop both.
**Rationale**: the upgrade is the moment the truth changes, the LLM is already
running `upgrade.md` then, and `UPGRADE_METADATA` already carries the exact
`from→to` range. A marker re-derives information we already have; a SessionStart
nudge uses a channel the LLM ignores (issue #32). The re-discovery CLI covers the
"reassess later" case without persistent state.

### Decision: `was` is natural language, matched semantically — no `detect:` probes

**Context**: The original design encoded machine-runnable grep probes per entry.
**Decision**: just write the `was` truth in plain language; the LLM finds it.
**Rationale**: LLMs are good at "find docs that say X and update them"; a shell
probe is brittle against paraphrasing and adds authoring burden for no gain in an
LLM-driven flow.

## Success Criteria

- [ ] A truth-changes YAML for v3.12.0 exists with the plan-number `was → now`
  entry; `check-truth-changes --from 3.11.0` prints it.
- [ ] `upgrade.md` instructs the LLM to reconcile project docs from truth-changes
  over the `(from, to]` range, editing/removing in the project's own docs only.
- [ ] Running the reconcile against a doc that still says "scan CLAUDE/Plan for
  the next number" updates it to the git-counter truth; a second run is a no-op.
- [ ] `plan_number_helper.get_claude_md()` renders the current git-counter truth
  in the `<hooksdaemon>` block.
- [ ] RELEASING.md moves `truth-changes/` at release.
- [ ] All QA passes; daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                     | Impact | Probability | Mitigation                                                                                                         |
| ---------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------------------ |
| Entries never authored (mechanism inert) | High   | Med         | One Step 7 checklist line; authoring one entry is two sentences                                                    |
| LLM edits the wrong/daemon files         | Med    | Low         | `upgrade.md` scopes edits to project docs, forbids `.claude/hooks-daemon/`; `daemon_location_guard` blocks `cd` in |
| Over-eager removal when `now` is empty   | Med    | Low         | Instruction: remove only the specific stale guidance, ask before deleting large sections                           |
| Semantic match misses paraphrased docs   | Low    | Med         | Acceptable — best-effort; the LLM is the matcher, not a regex                                                      |

## Notes & Updates

### 2026-06-04

- Plan created from a 4-agent ideation + triage cycle (archived in
  `archive/design1/`: `RESEARCH.md`, `ideation1-4.md`, `final-triage.md`), then
  **deliberately simplified** at user direction — the heavier marker/staleness/push design was cut as
  over-engineering. The exploration artifacts are retained as design history.
- Filed issue #32 (reframe SessionStart messages as human-only) — informs the
  "deliver via upgrade flow, not session message" decision here.
- Next plan number reserved via git counter `hooksdaemon.latestPlanNumber` (118).
- Delivery commit hash(es) to be recorded here on completion.
