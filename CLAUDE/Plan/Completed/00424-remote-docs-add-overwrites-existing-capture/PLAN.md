# Plan 00424: remote docs add overwrites existing capture

**Status**: Complete
**Created**: 2026-09-16
**GitHub Issue**: #42
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`hooks-daemon remote-docs add <url>` for a URL already captured in the tree
overwrites the existing file with no refusal, no flag and no report. Reproduced
on current `main`: two captures of one URL with a fetcher serving different
bodies land on the same destination, the first body does not survive, and the
second call returns normally. `write_capture` derives the destination and calls
`write_text` unconditionally; nothing on the CLI `add` path checks either.

The tree exists to hold hashed, dated evidence, so the loss is not merely a
replaced file: the recorded `fetched_at` and `source_sha256` move, and anything
citing the earlier hash now points at bytes that no longer exist.

**The complication that shapes the fix.** `add` landing on an existing capture
is also a DOCUMENTED remedy that the tool prints. `remote-docs check`, on
finding licence drift, tells the user to run plain `add` because
`known_sources` is consumed at capture time and never reaches an
already-vendored file, while `refresh` compares the source hash and would
report `unchanged`. Re-running `add` is the only route that re-derives
frontmatter. A bare "refuse when the destination exists" would therefore break
the one workflow the tool recommends, so the remedy line moves in the same
change.

## Goals

- `add` refuses an existing destination, naming the path, its `fetched_at` and
  its recorded `sha256`, and pointing at `refresh` or `--force`.
- `--force` replaces the capture and prints the old and new `sha256`, so a
  replacement is visible in the terminal and in shell history.
- `remote-docs check`'s licence-drift remedy names the `--force` form, so the
  tool's own advice stays runnable.
- A capture of a URL not yet in the tree is unaffected.

## Non-Goals

- **Retaining the previous capture under a dated suffix.** Issue #42 raises it
  as optional. It introduces a retention policy for the tree — what is kept,
  for how long, and whether `list`, `check` and the index should see retained
  copies — which is a product decision, not part of closing the data-loss hole.
- **Refusing only when the fetched body hash differs.** Considered and
  rejected: it would preserve the drift remedy with no flag, but makes the
  command's behaviour depend on remote state and still needs `--force` for the
  case where upstream changed AND the licence needs re-deriving.
- Changing `refresh`, which already reports its outcome and is the deliberate
  path for "fetch again and rewrite".
- Anything in issues #43 and #44. Same subsystem, filed minutes apart, but
  independent: #43 is index regeneration after a delete, #44 is a pair of
  contract questions.

## Tasks

### Phase 1: refuse, and make forcing visible

- [x] ✅ **Task 1.1**: RED — a test proving a second `add` of the same URL
  replaces the first capture's body and returns success.
- [x] ✅ **Task 1.2**: GREEN — `write_capture` refuses an existing destination
  unless forced, raising the error type the CLI already reports.
- [x] ✅ **Task 1.3**: `--force` on the CLI, printing the old and new `sha256`.
- [x] ✅ **Task 1.4**: `check`'s licence-drift remedy names the `--force` form.

### Phase 2: documentation

- [x] ✅ **Task 2.1**: `CLAUDE/RemoteDocs.md` records the refusal, the flag and
  why `add` onto an existing path was previously the drift remedy.
- [x] ✅ **Task 2.2**: a release note under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/` — this is user-visible, and a
  client's own docs could assert the old behaviour.

## Success Criteria

- [x] ✅ The RED test from Task 1.1 fails before the fix and passes after.
- [x] ✅ A second `add` without `--force` refuses and writes nothing.
- [x] ✅ `--force` replaces the capture and prints both hashes.
- [x] ✅ A first capture of a new URL is unchanged.
- [x] ✅ Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/01-remote-docs-add-refuses-an-existing-capture.md`
  — a behaviour change an operator will notice, including the licence-drift
  remedy now needing `--force`.
- [x] ✅ QA verified — but NOT by a green `llm_qa.py all` in the worktree, which
  is unachievable there for reasons unrelated to this change (ledger
  [00422 N6](../00422-niggles-ledger-fifteen/NIGGLES.md)). The run gave 24,894
  tests, 24,884 passed, **0 failed**, with 10 setup ERRORS and `smoke_test` 0/3
  — all of them the worktree's daemon socket path exceeding the 108-byte cap by
  one byte. Every one of those 10 passes on `main`: the five stop-hook and
  tool-use-error cases inside a 228-test run, and the five playbook cases in
  14.3s. `lint`, `magic_values`, `pyright` (1754 files) and `type_check` (628
  files) were green in the worktree; the single `format` violation was black
  auto-fixing a test file, already applied.

## Delivery & Milestones

- Filed by the issue-sdlc loop from issue #42, triaged actionable with a
  reproduction.
- Implemented on `worktree-issue-42-remote-docs-add-overwrite` at `ad8e79b3`,
  merged `--no-ff` at `08f8b9c9`, worktree and branch reaped.
- `0fc8b17f` is not part of the fix: filing this plan left the plan index's
  closing self-check disagreeing with its own bullets, which had been failing
  `test_repo_hygiene_check` in CI. Counted from disk and corrected there.
- Two findings recorded rather than carried: ledger
  [00422 N6](../00422-niggles-ledger-fifteen/NIGGLES.md) at `c8336d8c`, the
  worktree socket-path cap that makes the acceptance gates unrunnable and
  misreport why.
