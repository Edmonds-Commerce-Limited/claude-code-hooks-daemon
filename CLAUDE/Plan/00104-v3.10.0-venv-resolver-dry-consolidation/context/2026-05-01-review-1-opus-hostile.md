# Hostile Review of Plan 00104 v3.10.0

**Reviewer**: Opus 4.6 (code-reviewer agent, hostile prompt)
**Date**: 2026-05-01
**Verdict**: REJECT — re-plan required

## Summary

Two FATAL findings, six CRITICAL, three HIGH, three MEDIUM, one NIT.

The plan repeats v1-of-00103's critical sin in subtler form: bundling a
**misdiagnosed** bug-fix (Decision 2) with structural work, where the structural
work then rewrites the surface the bug-fix patches.

## FATAL findings

### F-1. Decision 2's root-cause attribution is FALSE

**Plan claim**: `write-venv-metadata` stores `python_path` from "the `python3`
argv[0] of the calling Python interpreter"; fix is to record `sys.executable`.

**Live code** (`src/claude_code_hooks_daemon/daemon/cli.py:1394-1416`):
`cmd_write_venv_metadata` already constructs `python_path` from the
`--venv-path` CLI argument and writes `str(python_binary.resolve())`.

**Verified by inspection of the actual venv on this machine**:

```
$ ls -la /workspace/untracked/venv-py311-66bbc57c/bin/python*
lrwxrwxrwx. bin/python      -> python3
lrwxrwxrwx. bin/python3     -> /usr/bin/python3
lrwxrwxrwx. bin/python3.11  -> python3

$ python -c "from pathlib import Path; print(Path('.../bin/python').resolve())"
/usr/bin/python3.11
```

`Path.resolve()` follows the symlink chain `python -> python3 -> /usr/bin/python3`
and returns the system Python. **The actual root cause is `.resolve()` at
`cli.py:1415`, not the use of `argv[0]` or absent `sys.executable`.**

The fix is to drop `.resolve()` (or use `.absolute()` which canonicalizes
without following symlinks). The "use `sys.executable`" fix proposed in
Decision 2 is a **no-op** when the caller invokes the CLI via the venv's
own `bin/python`, because `sys.executable` would itself be subject to the
same symlink chain on most platforms.

### F-2. Decision 2.B silently inverts Plan 00100 step-2 SSOT contract

**Plan claim**: `paths.py resolve-venv` should "prefer `{venv_dir}/bin/python`
(constructed from disk) over the stored `python_path` field — the metadata
field exists for tooling diagnostics, not as the source of truth."

**Live contract** (`paths.py:567-574`): step 2 is "Metadata-authoritative" —
returns `metadata.python_path` directly, fingerprint not recomputed. The
entire Plan 00100 architecture is metadata-as-SSOT (deliberately retired
v3.7.0's fingerprint reimplementation).

Decision 2.B re-introduces fingerprint reimplementation. Test case: project
with two `venv-*/` dirs, one matches `lock_hash`, the other matches
`{venv_dir}/bin/python` — disk-construction picks the wrong one.
**Task 2.1's regression test would codify this regression.**

## CRITICAL findings

- **C-1.** Phase 2 ships before Phase 1 hostile review completes — re-creates
  the v1 anti-pattern. (Note: this review IS Phase 1.2; addressing now.)
- **C-2.** Tasks 2.1-2.3 vs Phase 5 file-overlap — bug fixes WILL be churned.
  Mitigated by F-1's corrected diagnosis: Issue #4 is now a 1-line
  `cli.py:1415` change, no `paths.py` modification needed, no Phase 5
  overlap.
- **C-3.** Decision 3 self-bootstrap downloads from `main` — irreproducible
  (no version pin), MITM-able ("verify size" is theatre), no recursion guard.
  Remedy: pin to GitHub release tag, checksum against release artifact,
  pass `--already-bootstrapped` to `exec`d copy.
- **C-4.** Decision 4 silently widens `resolve_existing_venv_python` fail-fast
  contract. Plan undercounts callers (says 9, actual 11): includes
  `validate_worktrees.sh`, `rollback.sh`, `debug_hooks.sh` etc. Some need
  hard-fail. Phase 1 Task 1.1 must enumerate per-caller intent.
- **C-5.** F12 caller count is STILL wrong: plan asserts 9, grep returns 11.
  Success criterion "9 callers preserved" must be updated.
- **C-6.** Issue #5 retry loop unclear whether ADDS retry or REPLACES `sync -f`.
  `venv.sh:465` already does `sync -f "$venv_path" 2>/dev/null || sync` — the
  `2>/dev/null` violates the project's own MEMORY.md "silent fallback hides
  regressions" lesson and should be removed in this release.

## HIGH findings

- **H-1.** Phase 10 Task 10.3 acceptance gate for diagnostic scripts is
  hand-wavy. Diagnostic scripts (`daemon-cli.sh`, `health-check.sh`,
  `init-handlers.sh`) are NOT handlers and have no `get_acceptance_tests()`.
  Concrete mechanism needed: `tests/acceptance/test_diagnostic_scripts.py`
  with explicit injection into release pipeline Step 12.
- **H-2.** Issue #1 fix only covers `upgrade.sh`. The initially-deployed skill
  scripts `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh` are also
  shipped at install time and remain stale until a successful upgrade
  redeploys them. Plan must address self-update for these too.
- **H-3.** Self-install dogfooding mid-Phase-5 risk — a bad commit between
  5.6 / 5.7 / 5.8 leaves dev's own daemon broken with no recovery path.
  Need explicit per-micro-commit daemon-restart verification, not just
  per-phase.

## MEDIUM findings

- **M-1.** Plan does not say which `upgrade.sh` Decision 3 targets.
  Two locations: `scripts/upgrade.sh` and
  `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/upgrade.sh`.
- **M-2.** Decision 5 puts `uv.lock` in daemon's `.gitignore` — verify
  it's not already gitignored before assuming.
- **M-3.** Hot-path latency target "\<5ms median" has no baseline measurement.
  Phase 3 Task 3.3 measures only post-consolidation. Need before/after.

## NIT

- **N-1.** "11 release-pipeline gates" is referenced as 15 elsewhere
  (RELEASING.md says 15 numbered steps; QA gate is 11 sub-checks).
  Terminology collision.

## Bottom line from reviewer

> "The user's 'one plan' directive is a license to scope, not to skip Phase
> 1's diagnostic verification. Re-plan: open `cmd_write_venv_metadata`,
> reproduce Issue #4 against current code, find the *actual* mechanism
> (likely `Path.resolve()`), then update Decision 2."

## Verification of F-1 (post-review, before plan amendment)

Confirmed conclusively against live code on this machine. The `.resolve()`
call at `cli.py:1415` is the bug. `Path.absolute()` returns the venv path;
`Path.resolve()` returns the base interpreter. Fix is one line.
