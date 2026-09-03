# Plan 00327: hooks contract refresh audit

**Status**: Not Started
**Created**: 2026-09-03
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`contracts/claude-code-hooks/` vendors 33 hand-derived JSON schemas
describing what each Claude Code hook event carries and what it may return.
The daemon enforces itself against them, so a wrong claim in one is enforced
as if it were documented.

**Upstream has changed since the last audit.** The raw hooks documentation
now hashes to `e2462deb…`; `META.json` records `d514bf57…` and a
`last_audited_claude_code_version` of `2.1.252`. `contract_staleness` is
advising a refresh on every new session, and that advisory is correct.

This plan performs the refresh, following the procedure in
`docs/guides/HOOK-CONTRACT-REFRESH.md`, and folds the mechanisable half of
that procedure into the CLI so the next refresh starts from a command rather
than from prose.

Filed by Plan 00326 (D20), which established that the contract has nothing
the remote-docs subsystem can manage — it vendors derived schemas, not
documents — and that clearing the advisory needs a verified extraction audit
rather than a version bump. Rushing that audit is precisely the fabrication
failure the procedure exists to prevent, which is why it is here rather than
a tail-end task there.

## Goals

- Every per-event JSON file reflects the CURRENT upstream documentation,
  with each changed claim traceable to a verbatim sentence in the raw
  markdown.
- `META.json` updated (`fetch_date`, `docs_bytes`, `docs_sha256`,
  `last_audited_claude_code_version`) and `contract_staleness` silent again.
- The mechanisable steps — raw fetch, hash comparison against
  `META.json.docs_sha256` — available as one command, so the next refresh
  does not begin by re-deriving prose.

## Non-Goals

- **No automated extraction.** Turning documentation prose into contract
  claims stays a verified human/agent step (Plan 00271 Decision 3). A
  summarised fetch of this exact URL once fabricated a
  `permissionDecision: "escalate"` value appearing nowhere in the raw text;
  automating the step that caught that would be the wrong lesson.
- **No migration onto the remote-docs subsystem** — settled by Plan 00326
  D20 and not reopened here.
- **No claims invented from observation.** A field seen on a real payload
  but absent from the docs is a docs-gap finding, not a contract claim (the
  Plan 00326 Task 0.2 precedent: `effort` was added only once found
  verbatim upstream).

## Tasks

### Phase 1: Establish the delta

- [ ] ⬜ **Task 1.1**: Capture the raw markdown and confirm the hash differs
  from `META.json.docs_sha256`. `remote-docs add --verbatim` (Plan 00326
  D20) or the documented `curl` both give the response body unchanged. Keep
  the capture untracked — the procedure deliberately does not vendor it.
- [ ] ⬜ **Task 1.2**: Diff the new raw text against the last-audited state
  and write the list of CHANGED sections to a supporting document here, so
  the audit has a bounded worklist rather than 317 KB to re-read.

### Phase 2: The verified extraction

- [ ] ⬜ **Task 2.1**: For each changed section, update the affected
  `<Event>.json`, citing the verbatim supporting sentence in the audit
  document. Sections whose meaning did not change are recorded as
  checked-and-unchanged, so a later reader can tell "verified identical"
  from "not looked at".
- [ ] ⬜ **Task 2.2**: A newly documented event gets a new `<Event>.json`;
  the checker treats a documented event missing from the daemon's catalogue
  as a finding, which is the intended pressure.
- [ ] ⬜ **Task 2.3**: Re-run the contract QA checks and reconcile every
  finding — including stale `ALLOWLIST.yaml` / `INPUT-ALLOWLIST.yaml`
  entries, which fail QA when they no longer match a live finding.

### Phase 3: Close the loop

- [ ] ⬜ **Task 3.1**: Update `META.json`; confirm `contract_staleness` goes
  silent on a fresh session.
- [ ] ⬜ **Task 3.2**: Add a `contract-status` CLI command — raw-fetch the
  documented URL, compare its sha256 with `META.json.docs_sha256`, report
  unchanged/changed with an exit code. That is steps 1–2 of the procedure,
  which are pure mechanism; the extraction steps stay prose because they are
  judgement.
- [ ] ⬜ **Task 3.3**: Trim `HOOK-CONTRACT-REFRESH.md` to what remains
  genuinely manual, pointing at the new command for the rest. The
  RAW-fetch-only rule and its motivating incident stay verbatim — that is
  the part nobody may skim.

## Success Criteria

- [ ] `META.json.docs_sha256` matches the current upstream document.
- [ ] Every changed contract claim is traceable to a verbatim upstream
  sentence recorded in this plan's audit document.
- [ ] The contract QA checks pass with no stale allowlist entries.
- [ ] `contract_staleness` is silent on a new session.
- [ ] `hooks-daemon contract-status` reports the verdict without a manual
  `curl` + `sha256sum`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00327-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — Phase 1: the delta is known and bounded.
- Milestone B — Phase 2: the contract matches upstream, verified claim by claim.
- Milestone C — Phase 3: the advisory is clear, and the next refresh starts from a command.
