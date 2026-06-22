# Plan 00133: Suggest Enabling New Features on Upgrade

**Status**: In Progress
**Created**: 2026-06-22
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

This project ships behaviour-changing handler features as **opt-in** options so
that an upgrade never silently changes a client's behaviour. The side effect is
that those features arrive **dormant**: a client gets the new code but never the
new protection unless something actively tells them the capability exists and
how to turn it on. The motivating example is v3.23.0's *Block Untracked Claude
Memory* (`markdown_organization.allow_untracked_claude_memory`, default `True`)
— shipped, but inert in every client project because nothing promotes it.

An advisory mechanism for exactly this already exists — `config_migrations.py`
reads `CLAUDE/UPGRADES/config-changes/v{X.Y.Z}.yaml`, diffs the `added:` keys
against the client's actual config, and emits a `💡 New Options Available`
report. But it is **abandoned** (no manifests past v2.15.2), **unwired** (the
`check-config-migrations` CLI is never called from `upgrade.md`), and
**informational-only** (it lists options; it never *recommends* enabling a
dormant one). See `findings.md` for the full investigation and `context.md` for
the framing.

This plan revives, backfills, strengthens, and wires up that existing mechanism
— mirroring the proven truth-changes release discipline — so every upgrade
surfaces a recommendation-grade prompt for each dormant opt-in feature in the
version range crossed. It deliberately reuses config-changes rather than
inventing a parallel manifest (DRY / single source of truth).

## Goals

- Upgrading clients see a **recommendation-grade** suggestion to enable each
  dormant opt-in feature added since their previous version (memory-disable is
  the priority example).
- The config-changes advisory distinguishes **dormant** (default preserves old
  behaviour — needs an opt-in nudge) from **informational** (default already
  safe — FYI only) and marks options **recommended** where appropriate.
- `check-config-migrations` is wired into the post-upgrade flow (`upgrade.md`)
  alongside `check-truth-changes`.
- v3.x config-changes manifests are backfilled for all dormant opt-in options,
  so the advisory has data to report for real client upgrades.
- Release discipline is added so manifests never rot again (an
  `UNRELEASED/config-changes/` staging dir + RELEASING.md steps + Step 7
  checklist prompt), mirroring truth-changes governance.

> **Superseded by `plan-review-1.md` (Opus architect review) + user decisions
> 2026-06-22.** Final shape: **single release** (mechanism + memory default flip
>
> - dogfood bundled — user: "1 release is fine, avoid busywork"); adopt
>   `get_default_enabled()` now (concrete, default `True`); schema = two booleans
> - `recommended_value`; `changed:` becomes value-comparison-aware; migrated
>   memory is left inert (never auto-deleted); dogfood this repo before/within the
>   release. The task breakdown below is the reconciled single-release plan.

## Non-Goals

- **No auto-enabling of a client's config.** The advisory *suggests*; it never
  rewrites a client's existing setting. A client who explicitly set the old
  value keeps it and must act on the advisory (the merger preserves
  customisations). New installs / clients with no key inherit the new default.
- **No new parallel manifest subsystem** — reuse + strengthen config-changes.
- **No auto-deletion of source memory** during migration — leave inert,
  reversible; deletion is the user's explicit call.
- Not backfilling *every* config key ever added — focus on dormant opt-in
  options; neutral/default-safe additions are optional best-effort.

**Note:** the earlier "no behaviour change" non-goal is **dropped** — this
release deliberately flips `allow_untracked_claude_memory` to default-`False`
(opt-out), a semi-breaking change carrying an upgrade guide + `critical`
post-upgrade migration task.

## Context & Background

See `context.md` (the scene + user's words) and `findings.md` (investigation).
Key adjacent prior art to mirror: Plan 00118 truth-changes
(`install/truth_changes.py`, `cli check-truth-changes`, `upgrade.md` step 4,
RELEASING.md Steps 6/7, `UNRELEASED/truth-changes/` staging).

## Tasks

(Single-release plan, reconciled from `plan-review-1.md` section F. The review's
Phase 7 "mechanism release" and Phase 8 "flip release" are **collapsed into one
release** per user decision.)

### Phase 1: `get_default_enabled()` (TDD)

- [ ] ⬜ **Task 1.1**: RED — tests: base `Handler.get_default_enabled()` returns
  `True`; an opt-in handler overriding to `False`; `init_config` derives the
  `enabled:` flag from the declared default.
- [ ] ⬜ **Task 1.2**: GREEN — add concrete `get_default_enabled()` to `Handler`;
  override `→ False` on current opt-in handlers (audit template `enabled: false`
  entries, e.g. `lsp_enforcement`).
- [ ] ⬜ **Task 1.3**: Refactor `ConfigTemplate.generate_full` to derive enabled
  state from handler instances (removes hand-maintained literal duplication).
- [ ] ⬜ **Task 1.4**: Version-note comment near `_ABSTRACT_METHOD_VERSIONS`
  recording `get_default_enabled → <release>`.
- [ ] ⬜ **Task 1.5**: QA + daemon restart RUNNING.

### Phase 2: Schema + advisory strengthening (TDD)

- [ ] ⬜ **Task 2.1**: RED — tests: parse `recommended`/`dormant`/
  `recommended_value`; advisory **promotes** a dormant/recommended `added`
  distinctly; advisory **compares value** for a `changed` entry with
  `recommended_value` and warns when the client's value differs.
- [ ] ⬜ **Task 2.2**: GREEN — extend `ConfigChangeEntry` + parser; add a
  `🆕 Recommended — enable these` section above plain `💡 New Options Available`;
  implement the `changed`-value comparison (today `changed` is doc-only). Where
  cheap, auto-derive dormant opt-in **handlers** from `get_default_enabled()`.
- [ ] ⬜ **Task 2.3**: REFACTOR; update `config-changes/SCHEMA.md`.
- [ ] ⬜ **Task 2.4**: QA.

### Phase 3: Wire into the upgrade flow

- [ ] ⬜ **Task 3.1**: Add a `check-config-migrations` step to
  `skills/hooks-daemon/upgrade.md` alongside `check-truth-changes` (uses the
  `(from, to]` range from `UPGRADE_METADATA`).
- [ ] ⬜ **Task 3.2**: Mirror the v3.18.1 truth-changes treatment in
  `scripts/upgrade.sh` so a **bare** upgrade run also surfaces the advisory.
- [ ] ⬜ **Task 3.3**: Reconcile `CLAUDE/LLM-UPDATE.md` references.

### Phase 4: Backfill v3.x manifests

- [ ] ⬜ **Task 4.1**: Inventory opt-in options/handlers added v3.0 → v3.23.0,
  classified dormant vs. neutral (findings already names
  `allow_untracked_claude_memory`, `extra_allowed_markdown_paths`,
  `yolo_container_detection.show_on_session_start`).
- [ ] ⬜ **Task 4.2**: Author `config-changes/v{X.Y.Z}.yaml` for each.
- [ ] ⬜ **Task 4.3**: Sanity-check `cli check-config-migrations --from 3.0.0 --to <this release>` against a fixture config → dormant options promoted.

### Phase 5: Release discipline (anti-rot)

- [ ] ⬜ **Task 5.1**: Create `CLAUDE/UPGRADES/UNRELEASED/config-changes/` + README
  mirroring `UNRELEASED/truth-changes/README.md`.
- [ ] ⬜ **Task 5.2**: RELEASING.md step (near Step 6) to move staged manifests at
  release.
- [ ] ⬜ **Task 5.3**: Step 7 checklist line: "did this release add/flip an opt-in
  feature → config-changes entry with `recommended`/`dormant`/`recommended_value`
  exists?"

### Phase 6: Dogfood the memory migration (this repo)

- [ ] ⬜ **Task 6.1**: Execute Plan 00131 Phase 6 here — enable the policy in this
  repo, migrate this repo's `MEMORY.md` into tracked docs/rules using the
  `_deny_untracked_memory` rubric (also clears the current MEMORY.md overflow).
  Capture friction → feed into the post-upgrade task wording.

### Phase 7: Memory default flip (same release)

- [ ] ⬜ **Task 7.1**: RED/GREEN — flip `_allow_untracked_claude_memory` default
  `True → False` + the template default; update tests asserting default-blocking.
- [ ] ⬜ **Task 7.2**: config-changes manifest `changed: allow_untracked_claude_memory`
  with `recommended_value: false`, `recommended: true`.
- [ ] ⬜ **Task 7.3**: `critical` post-upgrade task
  `NN-migrate-untracked-claude-memory.md` (rubric / Phase-4 skill link;
  never auto-delete source).
- [ ] ⬜ **Task 7.4**: Upgrade guide `CLAUDE/UPGRADES/v3/...`; truth-changes entry
  if a documented "memory allowed" claim flips.
- [ ] ⬜ **Task 7.5**: `optimal_config_checker` reconciliation still correct under
  the flipped default (no "re-enable memory" nag).

### Phase 8: Verify & release

- [ ] ⬜ **Task 8.1**: Full QA `./scripts/qa/run_all.sh` (13/13) + H-1 gate (23/23).
- [ ] ⬜ **Task 8.2**: Daemon restart + status RUNNING; live-verify the flipped
  default blocks memory writes and the advisory promotes the change.
- [ ] ⬜ **Task 8.3**: Run `/release` — MINOR with upgrade guide (PreToolUse
  blocking handler default changed → full Step 12 acceptance applies).

## Dependencies

- Related: Plan 00118 (truth-changes — the template to mirror). Complete.
- Related: Plan 00131 (memory-disable — the priority feature to promote).
  Shipped v3.23.0.

## Technical Decisions

### Decision 1: Reuse config-changes vs. new manifest

**Context**: The user asked to add suggestions "as part of the upgrade
post-process (e.g. truth update)". A naive reading is "build a new
feature-suggestions manifest next to truth-changes."
**Decision**: **CONFIRMED.** Reuse and strengthen the existing **config-changes**
mechanism — it already loads per-version manifests, diffs against the client's
config, and has a CLI command. A parallel subsystem would duplicate the
loader/differ and violate DRY.
**Date**: 2026-06-22

### Decision 2: `get_default_enabled()` — adopt now, concrete, default `True`

**Decision**: Adopt as a **concrete** base method on `Handler` returning `True`
(not abstract — avoids breaking every project handler; most handlers are
opt-out). Opt-in handlers override `→ False`. `init_config` derives the
template `enabled:` flag from it (SSoT). Complementary to the manifest: it
models handler on/off; the manifest models option-level promotion.
**Date**: 2026-06-22 (user: "1 yes")

### Decision 3: Single release, bundle the flip

**Decision**: One release bundles mechanism + memory default flip + dogfood.
Overrides the review's two-release recommendation per user ("1 release is fine,
avoid busywork"). It is a **MINOR with an upgrade guide** (PreToolUse blocking
default changed), never a patch.
**Date**: 2026-06-22

### Decision 4: Schema = two booleans + `recommended_value`; `changed` value-aware

**Decision**: Add `recommended: bool`, `dormant: bool`, `recommended_value` to
manifest entries (minimal/additive over a nested `promote:` block — YAGNI).
Make `changed:` advisory-actionable via value comparison so a default flip
surfaces for clients holding the old value. Migrated memory is left **inert**
(never auto-deleted). **Date**: 2026-06-22 (user: "rest — recommended is fine")

### Decision 5: SSoT-by-verification, not full template derivation (Task 1.3)

**Context**: The review's Task 1.3 proposed refactoring
`ConfigTemplate.generate_full` to *derive* every `enabled:` flag from handler
instances. The template is a single curated YAML string carrying inline
comments, grouped priorities, and nested `options:` blocks (e.g.
`markdown_organization`, `tdd_enforcement`). A full data-driven rewrite would
destroy that curation and risk breaking every fresh `init` — high risk for a
cosmetic SSoT win, against the user's "avoid busywork".
**Decision**: Keep the curated template string; make `get_default_enabled()`
the **code-level SSoT for the semantic default** and add a drift-guard test
(`test_default_enabled_template_consistency.py`) asserting the set of
`enabled: false` handlers in `generate_full()` is identical to the set of
handler classes declaring `get_default_enabled() -> False`. The two sources
therefore cannot drift; adding an opt-in handler forces both to be updated.
The advisory (Phase 2) consumes `get_default_enabled()` directly, so it is not
dead code. **Date**: 2026-06-22

## Success Criteria

- [ ] `cli check-config-migrations --from <prev> --to 3.23.0` against a config
  lacking `allow_untracked_claude_memory: false` produces a clear
  **recommended/enable** suggestion for the memory feature.
- [ ] `upgrade.md` invokes the suggestion step; a bare upgrade surfaces it.
- [ ] v3.x dormant opt-in options have config-changes entries.
- [ ] `UNRELEASED/config-changes/` staging + RELEASING.md steps exist so future
  opt-in features are promoted automatically.
- [ ] QA 13/13, H-1 gate passes, daemon restarts RUNNING.
- [ ] No handler default or runtime behaviour changed.

## Risks & Mitigations

| Risk                                                                | Impact | Probability | Mitigation                                                                                                   |
| ------------------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------------ |
| Advisory becomes noisy (every option shouts "enable")               | Med    | Med         | `dormant`/`recommended` flags gate the strong nudge; neutral additions stay in the quiet `💡` bucket         |
| config-changes was intentionally retired in favour of truth-changes | Med    | Low         | Phase 1 git-history check before investing; if so, fold suggestion into truth-changes-style manifest instead |
| Backfill drifts from reality                                        | Low    | Med         | Cross-check each manifest entry against the release notes + actual handler option                            |

## Notes & Updates

### 2026-06-22

- Plan scaffolded (00133).
- Wrote `context.md` (scene + user's request) and `findings.md` (investigation).
- Investigation headline: the config-changes/`config_migrations` mechanism
  already exists for this purpose but is abandoned (no v3.x manifests), unwired
  (not called from `upgrade.md`), and informational-only (no recommend/enable
  promotion). Plan reframes the work as revive + strengthen + backfill + wire,
  not build-new.
