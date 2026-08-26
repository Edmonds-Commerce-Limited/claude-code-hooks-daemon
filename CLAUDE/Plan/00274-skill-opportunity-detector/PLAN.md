# Plan 00274: skill opportunity detector

**Status**: In Progress
**Created**: 2026-08-26
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A mechanism that helps a project notice when it is probably time to create a
skill (`.claude/skills/`): repeated near-identical requests, repeated
multi-step workflows, or points of confusion the user has to re-explain every
session. The evidence already exists in Claude Code's session transcripts
(`~/.claude/projects/<slug>/*.jsonl`); nobody re-reads them. This plan mines
them — periodically and on demand — and files a report of skill-creation
suggestions for human review.

Shape: a three-stage pipeline — deterministic extraction of genuine HUMAN
prompts from the jsonl (the crux; see `BRAINSTORM.md` §2 for the verified
transcript format and two-layer noise filter), deterministic
dedupe/normalise/cluster/redact aggregation, then one bounded Haiku call over
the condensed digest. Output is a report under `untracked/reports/` per Plan
00161 conventions. A SessionStart handler does NOT run the pipeline: it only
checks a TTL state file (≥ weekly cadence) and injects an advisory telling the
agent to run the `bin/hooks-daemon skill-scan` CLI, which is also the manual
entry point. Never auto-creates a skill. Ships disabled upstream;
dogfood-enabled in this repo. Full design exploration: `BRAINSTORM.md`.

## Goals

- A tested, deterministic transcript parser that extracts genuine human
  prompts, excluding tool results, `isMeta`/sidechain/compaction records,
  teammate messages, task notifications, cron ticks, interrupts, and
  machine-injected `/goal` lines.
- A deterministic aggregation stage (normalise, cluster, count across
  sessions/days, redact via `utils/secret_redaction`, cap the digest) that
  bounds Haiku input tokens and is the privacy bulwark.
- A `bin/hooks-daemon skill-scan` CLI (`--force`, `--window-days`, `--dry-run`)
  running the whole pipeline; Haiku invoked headlessly (`claude -p --model haiku`) per Plan 00266's Phase 1 findings, fail-open on every error.
- A TTL-gated advisory SessionStart handler (`skill_opportunity_detector`,
  default interval 7 days) using the `version_check` state-file pattern under
  the daemon untracked dir.
- Reports that suggest concrete new skills with evidence, suppress suggestions
  already covered by existing `.claude/skills/`/`.claude/commands/`, and never
  quote sensitive prompt content verbatim.
- Dogfooded here: enabled in this repo's config, run against this machine's
  real transcripts, suggestions reviewed.

## Non-Goals

- Never auto-create, scaffold, or commit a skill — report-only, human decides
  (00161's report-first boundary).
- No AI-decided hook outcomes — the model call lives in the CLI, outside every
  hook path; this does not revive Plan 00266's dormant phases.
- No reading of assistant output, tool results, or file contents beyond what
  the type filter needs to discard them.
- No embeddings/vector infrastructure — token-overlap clustering is enough
  for v1.
- No cross-project scanning in v1 (open question 5 in `BRAINSTORM.md` §9).
- No changes to the recovery-cron / idle-housekeeping machinery.

## Context & Background

- **Plan 00161 (idle housekeeping, In Progress)** established the report-first
  conventions this plan reuses: markdown reports in git-ignored
  `untracked/reports/`, advisory-delegation (handler advises, agent executes),
  never auto-fix/auto-commit, config-gated opt-in. See
  `docs/guides/CREATING_REPORTS.md`.
- **Plan 00266 (AI-assisted handler decisions, Dormant)** answered how a
  daemon-side model call works and what it costs: subprocess `claude -p` or
  the API, new infrastructure for timeout/error/mocking, fail-open mandatory,
  latency intolerable in hook paths (~1.2s vs ~51ms dispatch). 00274 is the
  concrete use case 00266 anticipated, consumed as reference — its findings
  are cited, not re-derived, and its revival conditions are not tripped.
- **Plan 00085** (reminder pseudo-event system) — related prior art for
  periodic, state-gated advisory nudging.
- Transcript format verified live on this machine (`BRAINSTORM.md` §2): field
  filters (`type`, `isMeta`, `isSidechain`, `isCompactSummary`, content shape)
  plus content-marker filters get from 10,433 "user" records to ~184 genuine
  prompts in a sampled real session file.
- TTL/state precedent: `src/claude_code_hooks_daemon/handlers/session_start/version_check.py`
  (`cached_at` + TTL compare, corrupt = expired, state under
  `ProjectContext.daemon_untracked_dir()`, never `/tmp`).

## Dependencies

- Related: Plan 00161 (report conventions; not blocking — the conventions and
  `CREATING_REPORTS.md` are already live)
- Related: Plan 00266 (Haiku-invocation research, consumed as reference)
- Related: Plan 00085 (advisory nudge prior art)

## Tasks

### Phase 1: Research, verification and spikes

- [x] ✅ **Task 1.1**: Transcript-format verification harness: DELIVERED by
  the `prototype/` (commit `4602b8fd`) — `ScanStats` counts every exclusion
  rule over the real files (20,829 user records → 142 genuine prompts), and
  `test_skill_scan.py` freezes the field/marker contract into synthetic
  inline fixtures (25 tests, no real transcript content committed).
- [x] ✅ **Task 1.2**: Haiku-invocation spike, citing Plan 00266: the dogfood
  run observed the no-auth failure mode — headless `claude -p` exits 1 "Not
  logged in" inside this container, so Decision 3's reuse-user-auth premise
  fails in containerised sessions. Resolved by Decision 5: v1 is CLI-auth
  only with the no-auth failure mode first-class (fail-open, report notes the
  skip and remedy). Latency/cost measurement deferred to the Task 5.2
  authenticated dogfood run.
- [x] ✅ **Task 1.3**: Clustering heuristic decided — see Decision 4
  (token-set Jaccard, threshold 0.5, measured over the real corpus).
- [x] ✅ **Task 1.4**: Open questions resolved by the user's rollout
  authorisation — recorded as Decisions 5–8 below.

### Phase 2: TDD — extraction and aggregation (deterministic core)

- [x] ✅ **Task 2.1**: Transcript reader delivered in
  `src/claude_code_hooks_daemon/skill_scan/extraction.py`: slug derivation,
  mtime windowing, streaming line parse, tolerant skip+count of unknown
  records, field-level exclusions.
- [x] ✅ **Task 2.2**: Content-level noise filter with
  `extra_exclude_patterns` config (constants + extraction tests freeze the
  marker contract).
- [x] ✅ **Task 2.3**: Normalisation, clustering, per-cluster aggregation,
  digest cap and representative truncation
  (`clustering.py`, `digest.py`, `models.py`).
- [x] ✅ **Task 2.4**: Redaction integration via
  `utils/secret_redaction.redact_text` in digest AND report; regression
  tests assert a secret term never reaches the model prompt or the report.

### Phase 3: TDD — CLI, Haiku stage and report

- [x] ✅ **Task 3.1**: `skill-scan` CLI subcommand (`--force`,
  `--window-days`, `--dry-run`, `--project-root`) in `daemon/cli.py`;
  model behind the `ModelInvoker` protocol, mocked in tests.
- [x] ✅ **Task 3.2**: Model stage (`invoker.py`): rubric prompt with
  existing-skill inventory; strict-JSON parse with degrade-to-raw-notes;
  fail-open on every external error; `last_attempt_at` vs `last_scan_at`
  in `state.py` so failures retry without nagging.
- [x] ✅ **Task 3.3**: Report writer (`report.py`) per `CREATING_REPORTS.md`:
  dated filename, privacy header, schema-drift canary, redacted snippets,
  workloads vs corrections sections, existing-skill suppression note.

### Phase 4: TDD — SessionStart handler and config

- [x] ✅ **Task 4.1**: `skill_opportunity_detector` handler
  (`SessionStartHandlerBase`, advisory, non-terminal, broad fail-open):
  TTL check via the version_check state pattern; advisory carries the full
  remedy at fire time (T4 exemption recorded in the guidance coverage
  suite — no resident CLAUDE.md section).
- [x] ✅ **Task 4.2**: Config surface shipped: `enabled: false` upstream
  default (template + `get_default_enabled`), all six options, constants,
  HandlerID/Priority registrations, `get_acceptance_tests()`,
  HANDLER_REFERENCE.md entry, `config-changes` UNRELEASED manifest entry
  (dormant, recommended for dev-heavy projects).

### Phase 5: Integration, dogfooding and closure

- [ ] 🔄 **Task 5.1**: Full QA green in the worktree (24/24, coverage
  95.1%); worktree daemon started RUNNING with the new code; dogfooding
  config tests pass. REMAINING on main after merge: dogfood daemon restart
  verification.
- [ ] ⬜ **Task 5.2**: Enable in this repo's `.claude/hooks-daemon.yaml`
  (stanza staged with `enabled: false`); run `skill-scan --force` against
  this machine's real transcripts; review the report with the user
  (including whether existing skills were correctly suppressed); record
  findings in JOURNAL/. Main-thread act after merge.
- [x] ✅ **Task 5.3**: Privacy exception noted in `CREATING_REPORTS.md`;
  client-mode verified via `scripts/dummy-client-repo.sh` (production
  installer; `cli skill-scan --dry-run` runs cleanly with an empty
  transcript window).

## Technical Decisions

### Decision 1: Advisory delegation, not inline or background execution

**Context**: SessionStart must stay fast; the pipeline is slow and calls a
model. **Options**: (a) inline in the handler — violates the daemon's latency
premise; (b) daemon-spawned background process — adds lifecycle machinery and
puts the model call in daemon-owned paths; (c) handler checks TTL only and
advises the agent to run the CLI. **Decision**: (c) — matches 00161's
report-first advisory-delegation pattern, keeps Haiku out of the daemon
process, and the CLI is the single pipeline for both cadenced and manual runs.
**Date**: 2026-08-26

### Decision 2: Privacy stance — condensed, redacted digests only

**Decision**: only Stage-1 human-prompt text is ever extracted; everything
sent to Haiku or written to a report is normalised, clustered, truncated and
passed through `utils/secret_redaction.redact_text`; reports carry a standing
review-before-sharing header and never quote prompts verbatim at length. The
feature ships disabled upstream — enabling it is the project's explicit
opt-in. Residual risk (list-based redaction cannot catch unlisted secrets) is
documented, and `--dry-run` exists as the audit view of exactly what would be
sent. **Date**: 2026-08-26

### Decision 3: Haiku via headless `claude -p`, fail-open, outside hook paths

**Decision**: invoke `claude -p --model haiku` (reusing the user's existing
Claude Code auth; API fallback only if Task 1.4 decides it is wanted), per
Plan 00266's mechanism research; every model-call failure degrades to a
logged skip and a partial report, never a block or crash; the call lives only
in the CLI, so no hook event ever waits on a model. **Date**: 2026-08-26

### Decision 4: Clustering — token-set Jaccard at threshold 0.5

**Context**: Task 1.3 compared token-set Jaccard against character-trigram
Jaccard over the real corpus (143 genuine prompts) at thresholds 0.3–0.6.
Both produced near-identical cluster structures at every threshold (e.g.
130 vs 130 clusters, 11 vs 11 multi-prompt clusters at 0.5); trigram gained
no additional true merges, made one questionable looser merge at 0.3, and ran
~4–5x slower. **Decision**: token-set Jaccard over normalised tokens with a
greedy threshold of 0.5 — simplest, fastest, dependency-free, and empirically
equivalent on this corpus. **Date**: 2026-08-26

### Decision 5: v1 model auth — CLI-only, no API-key fallback

**Decision**: v1 invokes only `claude -p --model <model>`; there is NO
`ANTHROPIC_API_KEY` fallback. The no-auth failure mode (observed in-container:
exit 1 "Not logged in") is first-class: fail-open, the report records the skip
reason and the remedy (log in, or run the scan from an authenticated
environment). The CLI works with the handler disabled — a manual run is
consent by definition; `enabled` gates only the SessionStart advisory.
**Date**: 2026-08-26

### Decision 6: Report retention — dated files

**Decision**: one dated report per scan,
`untracked/reports/YYYY-MM-DD-skill-opportunities.md` (Plan 00161 convention);
the TTL state file remembers the latest report path. **Date**: 2026-08-26

### Decision 7: Report separates WORKLOADS from CORRECTIONS

**Decision**: the model rubric asks for two sections — repeated workloads
(skill candidates) and recurring corrections/confusion (which may want a
doc/CLAUDE.md/rules line rather than a skill) — and the report renders both.
**Date**: 2026-08-26

### Decision 8: Cross-project scanning stays out of scope for v1

**Decision**: confirmed by the user; already listed in Non-Goals.
**Date**: 2026-08-26

## Success Criteria

- [ ] Parser unit tests cover every exclusion rule in `BRAINSTORM.md` §2
  against synthetic fixtures; no real transcript content committed.
- [ ] `skill-scan --dry-run` on this repo produces a digest containing zero
  secret-word-list terms (mechanically checked in a test).
- [ ] `skill-scan` with the model mocked produces a report matching the
  `CREATING_REPORTS.md` shape at the expected path.
- [ ] With the `claude` CLI absent (PATH manipulation in test), the CLI exits
  0 with a partial report and a logged skip reason; SessionStart is never
  blocked in any failure mode.
- [ ] Handler advises at most once per `check_interval_days` (state-file
  test); `--force` bypasses the TTL.
- [ ] Suggestions covered by an existing `.claude/skills/`/`.claude/commands/`
  entry are suppressed (test with a fixture inventory).
- [ ] Ships `enabled: false` upstream (default-config test); enabled in this
  repo's config; a real dogfood run reviewed with the user.
- [ ] Full QA passes; daemon restart RUNNING; acceptance tests present in the
  generated playbook.

## Risks & Mitigations

| Risk                                                    | Impact | Probability | Mitigation                                                                                            |
| ------------------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------------------------------------- |
| Sensitive prompt content leaks into a report/Haiku call | High   | Medium      | Decision 2 pipeline; redaction regression tests; `--dry-run` audit; disabled upstream                 |
| Claude Code changes the jsonl format silently           | Medium | Medium      | Tolerant parser (skip+count), schema-drift canary in report, Task 1.1 harness re-runnable             |
| Haiku output is garbage or the call fails               | Low    | High        | Strict-JSON parse with degrade-to-notes; fail-open everywhere; partial reports                        |
| Noise filter misses a machine-prompt shape              | Medium | Medium      | `extra_exclude_patterns` config; dogfood review (Task 5.2) tunes the built-in list against real noise |
| Suggestion fatigue / low-value reports                  | Medium | Medium      | Weekly-or-longer TTL floor, distinct-session ranking, existing-skill suppression, human-review output |
| Cost of the model call creeps                           | Low    | Low         | Digest cap bounds tokens; Task 1.2 measures real cost before build; single call per scan              |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00274-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
