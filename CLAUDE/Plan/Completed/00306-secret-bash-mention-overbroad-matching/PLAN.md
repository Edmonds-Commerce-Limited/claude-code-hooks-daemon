# Plan 00306: secret bash mention overbroad matching

**Status**: Complete
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

While fixing Plan 00305 Task 2.5 (secret_file_guard Edit-path false positive
on the Python list literal `[pass_result, fail_result]`), the implementing
agent repeatedly tripped `R-SECRET-BASH-MENTION` on Bash commands containing
plain words with "secret" in them — no `.secret` path literal, no protected
file named. That is the same over-broad-matching defect class as Task 2.5,
but in the Bash-mention detection path rather than the Edit/new_string path,
so it was out of that task's scope and is ledgered here instead (Plan 00157
"never drop a finding").

A guard that false-fires on ordinary words invites being disabled, which
costs more than the false positive itself — the fix must tighten matching
without weakening genuine protected-path detection.

## Goals

- Reproduce the false positive with a pinned failing test (a Bash command
  mentioning a plain word containing "secret" that names no protected path).
- Tighten the Bash-mention matching so plain-word substrings do not match
  protected-path globs, while all existing genuine-mention tests stay green.

## Non-Goals

- Revisiting the Edit-path matching (fixed in Plan 00305 Task 2.5).
- Weakening any deny that fires on a genuine protected-path mention.

## Tasks

### Phase 1: Reproduce and fix

- [x] ✅ **Task 1.1**: Reproduce the false positive from the Plan 00305
  journal context (grep/utility commands whose text contained plain words
  with "secret") and pin it with a failing unit test against the
  Bash-mention matching path.

- [x] ✅ **Task 1.2**: Tighten the matching (likely the same
  complete-bracket/glob-shape discipline applied in
  `utils/secret_file_matching.py` for Task 2.5) so the pinned test passes
  with the full existing secret_file_guard suite green.

- [x] ✅ **Task 1.3**: The daemon contradicts itself on secret-file
  untracking: `secret_file_hygiene_checker` instructs the agent to run
  `git rm --cached <path>` on a git-tracked protected path, but
  `R-SECRET-BASH-MENTION` denies ANY Bash command whose text mentions that
  path — so the daemon's own recommended remediation is un-runnable
  verbatim (observed live: untracking `.claude/block-words.secret.example`
  required a `git rm --cached '.claude/block-words.*'` pathspec-glob
  workaround). `git rm --cached` never reads file content; it only
  improves the exact hygiene the checker polices. Fix: exempt
  `git rm --cached <protected-path>` in the secret_file_guard Bash-mention
  path (same trusted-consumer discipline as the existing flag-position
  exemptions), pinned by a TDD test, so the hygiene checker's instruction
  works as printed. Keep every content-reading command denied.

### Phase 2: v3.58.1 code-review non-blocking findings (same subsystem)

- [x] ✅ **Task 2.1**: `daemon/cli.py` `_collect_secret_redaction_status_lines`
  reads only the primary root's `.claude/hooks-daemon.yaml`, while its sibling
  `_collect_enforcement_status_lines` iterates all `ProjectRegistry` roots —
  in a monorepo a sub-project with an absolute `secret_word_list_path`
  degrades silently and `check` prints OK. Iterate the same registry roots
  (or soften the `secret_redaction.py` docstring claim).

- [x] ✅ **Task 2.2**: `utils/secret_file_matching.py`
  `_has_leading_wildcard` — `_BRACKET_EXPRESSION_RE.match()` is anchored, so
  the `match.start() == 0` comparison is dead; return `match is not None`.

- [x] ✅ **Task 2.3**: `utils/secret_file_matching.py`
  `_has_trailing_wildcard` — the POSIX "literal `]` first" form `x[]]` is no
  longer reported as trailing-wildcard (still caught by the literal
  `path_matches_globs` pass, so not release-relevant). For exactness, allow
  an optional leading `]` in the character class: `\[!?\]?[^\]]*\]`.

- [x] ✅ **Task 2.4** (cosmetic): every pipe_blocker deny prints the
  "To disable: handlers.pre_tool_use.pipe_blocker" line twice (observed
  across all deny shapes in the v3.58.1 acceptance run). De-duplicate.

## Success Criteria

- [x] False positive pinned and fixed with TDD; full QA green; daemon
  restarted and verified.

## Delivery & Milestones

- `49befa8b` — Tasks 1.1-1.3, 2.1-2.4 delivered: secret_file_guard
  Bash-mention both-edges-wildcard false positive fixed (both the
  leading-wildcard overlap heuristic and the pre-existing
  substring+fnmatch check), `git rm --cached` exemption, CLI secret
  redaction status collector now iterates all `ProjectRegistry` roots,
  `_has_leading_wildcard` dead-code removal, `_has_trailing_wildcard`
  POSIX literal-bracket-first support, pipe_blocker duplicate
  disable-footer de-duplication. 78/78 `test_secret_file_matching.py`,
  6/6 `test_cli_secret_redaction_status.py`, 312/312 pipe_blocker suite
  green; full repo suite 17015 passed (2 pre-existing unrelated failures:
  `CLAUDE/Plan/README.md` size ceiling, 3 semgrep-not-installed errors —
  neither touches files changed here). Daemon restarted and verified
  RUNNING before commit; both false-positive repro commands
  (`find -iname "*secret_file*matching*"` and the commit message itself)
  confirmed clean live post-restart.
