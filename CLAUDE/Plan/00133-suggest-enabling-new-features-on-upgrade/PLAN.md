# Plan 00133: Suggest Enabling New Features on Upgrade

**Status**: Not Started
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

## Non-Goals

- **No auto-enabling.** The advisory suggests; it never mutates a client's
  config. Enabling is a deliberate client decision (matches truth-changes
  "guidance, not mutation").
- **No new parallel manifest subsystem** if config-changes can be extended.
- **No change to any handler's runtime behaviour or defaults.** This plan is
  data + advisory wording + wiring + docs only.
- Not backfilling *every* config key ever added — focus on dormant opt-in
  options; neutral/default-safe additions are optional best-effort.

## Context & Background

See `context.md` (the scene + user's words) and `findings.md` (investigation).
Key adjacent prior art to mirror: Plan 00118 truth-changes
(`install/truth_changes.py`, `cli check-truth-changes`, `upgrade.md` step 4,
RELEASING.md Steps 6/7, `UNRELEASED/truth-changes/` staging).

## Tasks

### Phase 1: Confirm scope & design (no code)

- [ ] ⬜ **Task 1.1**: Read `config_migrations.py` end-to-end; confirm the
  diff-against-client-config logic and the three advisory buckets.
- [ ] ⬜ **Task 1.2**: Check git history for whether `check-config-migrations`
  was ever wired into `upgrade.md`/`LLM-UPDATE.md` and later dropped.
- [ ] ⬜ **Task 1.3**: Decide schema approach — extend config-changes `added`
  entries with `recommended: bool` + `dormant: bool` (leaning) vs. a
  `promote:` sub-block. Record as a Technical Decision below.
- [ ] ⬜ **Task 1.4**: Inventory every opt-in option added across v3.0 → v3.23.0
  (grep handler `options` + release notes), classified dormant vs. neutral.
  Output the list into `findings.md` (append section).

### Phase 2: Schema + advisory strengthening (TDD)

- [ ] ⬜ **Task 2.1**: RED — tests for the new schema field(s) on
  `ConfigChangeEntry` and for the advisory promoting a `recommended`/
  `dormant` option distinctly from a neutral one.
- [ ] ⬜ **Task 2.2**: GREEN — extend the dataclass + manifest parser + advisory
  renderer; add a dedicated `🆕 Recommended — enable these` (or similar)
  section above plain `💡 New Options Available`.
- [ ] ⬜ **Task 2.3**: REFACTOR; update `config-changes/SCHEMA.md`.
- [ ] ⬜ **Task 2.4**: Run QA: `./scripts/qa/llm_qa.py all`.

### Phase 3: Wire into the upgrade flow

- [ ] ⬜ **Task 3.1**: Add a `check-config-migrations` step to
  `skills/hooks-daemon/upgrade.md` alongside `check-truth-changes`, using
  the `(from, to]` range from `UPGRADE_METADATA`.
- [ ] ⬜ **Task 3.2**: Verify the canonical `scripts/upgrade.sh` surfaces the
  advisory on a bare run (mirror the v3.18.1 truth-changes treatment), if
  appropriate.
- [ ] ⬜ **Task 3.3**: Update `LLM-UPDATE.md` to reference the suggestion step.

### Phase 4: Backfill v3.x manifests

- [ ] ⬜ **Task 4.1**: Author `config-changes/v{X.Y.Z}.yaml` for every v3.x
  release that added a dormant opt-in option, with `recommended`/`dormant`
  set. **Priority: v3.23.0 memory-disable entry.**
- [ ] ⬜ **Task 4.2**: Sanity-check via `cli check-config-migrations     --from 3.0.0 --to 3.23.0` against a fixture config missing the options →
  advisory should promote the dormant ones.

### Phase 5: Release discipline (anti-rot)

- [ ] ⬜ **Task 5.1**: Create `CLAUDE/UPGRADES/UNRELEASED/config-changes/` with a
  README mirroring `UNRELEASED/truth-changes/README.md`.
- [ ] ⬜ **Task 5.2**: Add a RELEASING.md step (near Step 6) to move staged
  `UNRELEASED/config-changes/` manifests into `config-changes/` at release.
- [ ] ⬜ **Task 5.3**: Add a Step 7 (Opus doc review) checklist line: "did this
  release add an opt-in option that should be promoted? → config-changes
  entry with `recommended/dormant` exists."

### Phase 6: Verify, dogfood, release

- [ ] ⬜ **Task 6.1**: Full QA `./scripts/qa/run_all.sh` (13/13) + H-1 gate.
- [ ] ⬜ **Task 6.2**: Daemon restart + status RUNNING.
- [ ] ⬜ **Task 6.3**: Decide bump level (schema field leans MINOR; pure
  data+wiring could be PATCH) and run `/release`.

## Dependencies

- Related: Plan 00118 (truth-changes — the template to mirror). Complete.
- Related: Plan 00131 (memory-disable — the priority feature to promote).
  Shipped v3.23.0.

## Technical Decisions

### Decision 1: Reuse config-changes vs. new manifest

**Context**: The user asked to add suggestions "as part of the upgrade
post-process (e.g. truth update)". A naive reading is "build a new
feature-suggestions manifest next to truth-changes."
**Decision (provisional)**: Reuse and strengthen the existing **config-changes**
mechanism — it already loads per-version manifests, already diffs added keys
against the client's config, and already has a CLI command. Building a parallel
subsystem would duplicate that loader/differ and violate DRY.
**To confirm in Phase 1** before writing code.
**Date**: 2026-06-22

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
