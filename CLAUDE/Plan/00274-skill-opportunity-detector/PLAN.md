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
- [ ] 🔄 **Task 1.2**: Haiku-invocation spike, citing Plan 00266: run
  `claude -p --model haiku --output-format json` headlessly with a
  digest-shaped prompt; MEASURE latency and cost per invocation (00266 rule:
  measured, never estimated); document auth prerequisites and every failure
  mode observed (no CLI, no auth, offline, timeout, malformed output).
  PARTIAL: dogfood run observed the no-auth failure mode — headless
  `claude -p` exits 1 "Not logged in" inside this container, so Decision 3's
  reuse-user-auth premise fails in containerised sessions; latency/cost
  measurement blocked until an authenticated environment or the Task 1.4
  API-fallback decision.
- [ ] ⬜ **Task 1.3**: Decide the clustering heuristic (token-set Jaccard vs
  trigram overlap) by running both over the real corpus via the Task 1.1
  harness; record the choice and threshold as a Technical Decision.
- [ ] ⬜ **Task 1.4**: Resolve the open questions in `BRAINSTORM.md` §9 with
  the user (CLI-without-handler, API fallback, report retention, corrections
  vs workloads sections, cross-project scope) and record answers as Technical
  Decisions here.

### Phase 2: TDD — extraction and aggregation (deterministic core)

- [ ] ⬜ **Task 2.1**: RED/GREEN/REFACTOR the transcript reader: project-slug
  derivation, mtime windowing, streaming line parse, tolerant of unknown
  record types (skip + count), field-level exclusions.
- [ ] ⬜ **Task 2.2**: TDD the content-level noise filter (teammate messages,
  task notifications, `FAILSAFE RECOVERY CHECK`, interrupts, `/goal`
  machine-marker, command echoes) with `extra_exclude_patterns` config.
- [ ] ⬜ **Task 2.3**: TDD normalisation (path/sha/number placeholders),
  clustering, per-cluster aggregation (counts, distinct sessions/days, date
  range), digest cap (`max_prompts`) and representative truncation.
- [ ] ⬜ **Task 2.4**: TDD redaction integration: every representative passes
  through `utils/secret_redaction.redact_text` before it can reach the digest
  or a report; regression test that a secret-list term never appears in
  either.

### Phase 3: TDD — CLI, Haiku stage and report

- [ ] ⬜ **Task 3.1**: TDD the `skill-scan` CLI subcommand (`--force`,
  `--window-days`, `--dry-run`); `--dry-run` prints the digest and skips the
  model call (doubling as the privacy audit view); model call behind an
  injectable dependency so tests mock it (00266 pattern).
- [ ] ⬜ **Task 3.2**: TDD the Haiku stage: prompt assembly including the
  existing-skill/command inventory and rubric; strict-JSON parse with
  degrade-to-raw-notes on garbage; fail-open (skip + logged reason + partial
  report) on every external error; `last_attempt_at` vs `last_scan_at` state
  so failures retry without nagging.
- [ ] ⬜ **Task 3.3**: TDD report generation per `CREATING_REPORTS.md`
  (`untracked/reports/YYYY-MM-DD-skill-opportunities.md`): summarised
  clusters with short redacted snippets only, existing-skill suppression
  noted, schema-drift canary line, standing "derived from private transcripts
  — review before sharing" header.

### Phase 4: TDD — SessionStart handler and config

- [ ] ⬜ **Task 4.1**: TDD `skill_opportunity_detector`
  (`SessionStartHandlerBase`, advisory, non-blocking): TTL check via the
  version_check state pattern; when due, inject "a skill-scan is due — run
  `bin/hooks-daemon skill-scan`"; silent otherwise; can never fail session
  start.
- [ ] ⬜ **Task 4.2**: Config surface per `BRAINSTORM.md` §6 (`enabled: false`
  upstream default, `check_interval_days`, `transcript_window_days`, `model`,
  `max_prompts`, `extra_exclude_patterns`, transcript-dir override);
  `get_claude_md()` guidance; `get_acceptance_tests()`; constants (no magic
  values); HANDLER_REFERENCE.md entry; `config-changes` UNRELEASED manifest
  entry.

### Phase 5: Integration, dogfooding and closure

- [ ] ⬜ **Task 5.1**: Full QA (`./scripts/qa/llm_qa.py all`), daemon restart
  RUNNING, dogfooding config tests pass.
- [ ] ⬜ **Task 5.2**: Enable in this repo's `.claude/hooks-daemon.yaml`; run
  `skill-scan --force` against this machine's real transcripts; review the
  report with the user (including whether existing skills were correctly
  suppressed); record findings in JOURNAL/.
- [ ] ⬜ **Task 5.3**: Docs: note the transcript-derived-content privacy
  exception in `CREATING_REPORTS.md`; verify client-mode behaviour
  (`scripts/dummy-client-repo.sh`) since the CLI touches paths outside the
  project root.

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
