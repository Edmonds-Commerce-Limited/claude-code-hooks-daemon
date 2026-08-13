# Plan 00233: Remove the Transcript Archiver

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The PreCompact `transcript_archiver` handler copies the session transcript into
`untracked/transcripts/` on every compaction. Investigation while closing Plan
00232 found that it protects nothing:

- **Compaction never deletes the original.** This session compacted five times
  and its transcript is still on disk, growing.
- **The original already lives on the persistent mount.**
  `~/.claude/projects` resolves to `/workspace/.claude/ccy/projects` — the same
  host bind mount, the same physical disk, the same project directory as the
  archives. Both are gitignored, nothing is tracked.
- **Nothing reads the archives.** Three references exist and none consumes
  their content: a disk-usage row in `daemon/cli.py`, a retention entry that
  bounds a directory which only exists to be bounded, and a line in
  `skills/hooks-daemon/report.md` telling an agent it may read them during bug
  triage. No code has ever parsed one.

The handler dates to the initial commit and was never justified against a
stated need, which is likely why nobody noticed it had accumulated **422 MB of
copies guarding 302 MB of originals** — including five copies of a single
session in one day, each a strict prefix of the next.

Removing it is the correct resolution: there is no requirement to reimplement
elsewhere, because there was no requirement in the first place.

## Goals

- Remove the handler, its registration, config, docs and tests
- Reclaim the 422 MB of accumulated archives
- Leave a client whose config still names the handler working, not broken
- Record the removal in the UNRELEASED manifests so upgrading projects are told

## Non-Goals

- **Redacting the original transcripts.** Considered and rejected for now: the
  daemon runs inside Claude Code sessions, so the current session's transcript
  always has a live writer, and redaction shifts every following byte. Writing
  to another tool's live data files is a different class of act from reading
  them. If this is ever wanted it needs its own plan, and the safe shape is an
  explicitly human-invoked scrub of transcripts with no live writer.
- Changing `sensitive_content`, which prevents secrets being written in the
  first place and is unaffected by any of this.
- Removing `scripts/qa/semgrep/unbounded-source-reads.yaml` (Plan 00232). The
  rule guards the class, not the deleted instance, and `TranscriptReader` is
  still a live unbounded-source read path.

## Context & Background

Plan 00232 made this handler's whole-file read 922x cheaper in memory. That
work was sound as far as it went and the measurement was real (673.5 MB peak at
PreCompact), but it optimised the cost of an operation whose value was never
questioned. The correct answer to "this copy is expensive" turned out to be
"this copy should not exist".

The plan is kept as history rather than reverted: its semgrep rule, its fixture
and its non-vacuity test all outlive the handler.

## Tasks

### Phase 1: Prove a client is not broken by the removal

- [x] ✅ **Task 1.1**: Confirm config loading tolerates a handler key the daemon
  no longer ships — it does, but this proved to be the WRONG layer and the
  result was misleading (see Decision 3)
- [x] ✅ **Task 1.2**: Remove the handler while DELIBERATELY leaving the config
  key in place, restart, and confirm the daemon runs — this reproduces the
  client upgrade path exactly rather than approximating it. **It failed**: the
  daemon came up in DEGRADED MODE
- [x] ✅ **Task 1.3**: Add a retired-handler registry so a removal never
  degrades a client's daemon (Decision 3), with a test proving typos are still
  caught

### Phase 2: Remove the code

- [x] ✅ **Task 2.1**: Delete the handler and its unit tests
- [x] ✅ **Task 2.2**: Remove the `pre_compact/__init__.py` export
- [x] ✅ **Task 2.3**: Remove `HandlerID.TRANSCRIPT_ARCHIVER`, the `HandlerKey`
  literal, and `Priority.TRANSCRIPT_ARCHIVER`
- [x] ✅ **Task 2.4**: Remove it from `install/handler_profiles.py` and the
  scaffold text in `daemon/init_config.py`
- [x] ✅ **Task 2.5**: Remove the integration-test class and the guidance
  coverage entry
- [x] ✅ **Task 2.6**: Remove its `error_hiding_exclusions.json` entry, and the
  cross-reference to it in the `compaction_signal` entry's reason text

### Phase 3: Remove the config, docs and data

- [x] ✅ **Task 3.1**: Remove the handler block from `.claude/hooks-daemon.yaml`
- [x] ✅ **Task 3.2**: Remove its sections from `docs/guides/HANDLER_REFERENCE.md`
- [x] ✅ **Task 3.3**: Remove the archive-reading guidance from `report.md`
- [x] ✅ **Task 3.4**: Update the `secret_redaction` docstring, which lists the
  archiver as one of the leak vectors it feeds
- [x] ✅ **Task 3.5**: Regenerate `.claude/HOOKS-DAEMON.md`
- [x] ✅ **Task 3.6**: Delete the 422 MB of accumulated archives

### Phase 4: Tell upgrading projects

- [x] ✅ **Task 4.1**: Stage a `config-changes` manifest entry (key removed)
- [x] ✅ **Task 4.2**: Stage a `truth-changes` manifest entry — the statement
  "transcripts are archived before compaction" becomes false

### Phase 5: Verify

- [x] ✅ **Task 5.1**: Full QA green — 21/21 after fixing a RUF022 `__all__`
  sort regression the removal itself introduced
- [x] ✅ **Task 5.2**: Daemon restarts RUNNING with PreCompact still dispatching
  its remaining handler
- [x] ✅ **Task 5.3**: Drive a real PreCompact event and confirm no archive is
  written and nothing errors — verified twice: this session's own 15:19
  compaction fired the real hook with the handler already gone, and an explicit
  probe through `.claude/hooks/pre-compact` returned `{}` / exit 0.
  `untracked/transcripts/` was not recreated by either

## Technical Decisions

### Decision 1: Delete rather than default-disable

**Context**: A softer option is to ship it disabled by default.

**Decision**: Delete. A disabled handler is still code to maintain, still
documented, still a config key people ask about, and still an invitation to
re-enable something that protects nothing. The retention machinery, the
disk-usage row and the doc guidance all exist only to service it. Nothing reads
the archives, so there is no user whose workflow degrades.

**Date**: 2026-08-13

### Decision 2: Delete the accumulated archives too

**Context**: The 422 MB already on disk is untracked and gitignored.

**Decision**: Delete, as explicitly requested. They are copies of transcripts
that still exist in `.claude/ccy/projects/`, so nothing is lost. Worth noting
plainly: those copies are the REDACTED ones and the surviving originals are
not, so this removes redacted duplicates while leaving unredacted originals —
which is an argument about the originals, not a reason to keep duplicates.

**Date**: 2026-08-13

### Decision 3: A retired-handler registry, because removal degraded clients

**Context**: Task 1.2 removed the handler while deliberately leaving the config
key, to reproduce a client's upgrade. The daemon came up in **DEGRADED MODE**:
`Unknown handler 'transcript_archiver'`. Every client with that key would see
that on every session until they hand-edited their config.

This contradicted a prediction made minutes earlier. `Config.load_or_default()`
tolerates unknown keys, and that was tested and taken as the answer — but the
runtime check lives in a *different* layer,
`src/claude_code_hooks_daemon/config/validator.py`. Testing the convenient
layer is what made the wrong answer look verified.

**Decision**: Add `RETIRED_HANDLERS`, a registry of config keys for handlers
the daemon deliberately removed. The validator exempts those names; everything
else stays a hard error.

The reasoning is about whose mistake it is. A client's config is their file.
Removing a handler upstream does not remove their key, so reporting it as a
configuration error blames the user for our decision — and gives them nothing
to act on until they read an upgrade note. Retirements belong in the upgrade
manifests, which is where they now go.

This is deliberately **not** a general escape hatch: an entry is added by hand,
in the commit that removes the handler. A pinned test asserts typos still fail,
because typo detection is the entire reason handler-name validation exists.

**Why it matters beyond this plan**: `transcript_archiver` is the first handler
ever removed, so this trap was unsprung until now. Any future removal would
have hit it. The registry is the guard for the class, not for this instance.

**Date**: 2026-08-13

## Success Criteria

- [ ] Daemon RUNNING with the handler gone AND a stale config key still present
- [ ] A real PreCompact event writes no archive and logs no error
- [ ] Full QA green
- [ ] `untracked/transcripts/` reclaimed
- [ ] UNRELEASED config-changes and truth-changes entries staged

## Risks & Mitigations

| Risk                                                    | Impact | Probability | Mitigation                                                                |
| ------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------- |
| A client's stale config key breaks their daemon         | High   | Low         | Reproduced deliberately in Task 1.2 before cleaning our own config        |
| Removal misses a reference and the daemon fails to load | Medium | Medium      | Full reference sweep done up front; daemon restart is the definitive gate |
| Someone later re-adds archiving without the context     | Low    | Medium      | Rationale recorded here and in the truth-changes manifest                 |

## Delivery & Milestones

- Delivered as a single commit — the removal, the retired-handler registry that
  makes it safe for clients, both UNRELEASED manifests, and this closure.
- Verified at delivery: QA 21/21; daemon RUNNING with a stale
  `transcript_archiver:` key still present in config and **0** validation
  errors; a real 15:19 compaction plus an explicit `.claude/hooks/pre-compact`
  probe both writing no archive; 422 MB reclaimed.
- Opened downstream: **Plan 00234** (handler value audit) — the same question
  asked systematically across every remaining handler.
