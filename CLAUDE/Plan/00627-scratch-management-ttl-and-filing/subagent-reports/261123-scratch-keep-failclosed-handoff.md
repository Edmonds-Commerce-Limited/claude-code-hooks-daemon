# Handoff: R-SCRATCH-KEEP-MARKER fails closed; truth-changes v3.76.0 -> v3.77.0

Branch `scratch-keep-failclosed` (from origin/main ab326aad0), pushed. Not merged.

## Unit 1: keep-marker guard fails closed on unlexable commands

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/scratch_keep_marker_guard.py`:
  `_bash_writes_marker` now returns True when `peeled_statements` raises
  `UnparseableCommand` (it only gets there when the command text names
  `.scratch-keep`), so the handler denies with the standard message, like
  R-SCRATCH-CAP (whose statement scan yields an unknown target on the same
  exception). The `log_and_continue` swallow is gone; an info log records it.
  `get_claude_md` guidance names the new route.
- Tests: `TestUnlexableStatementRoutes` (pinned "allows") became
  `TestUnlexableStatementRoutesFailClosed`: the two `$'...'` cases now deny,
  plus two unbalanced-quote cases (cp into a directory, `sh -c` body) and an
  allow case for unlexable text that does not name the marker. RED confirmed
  (2 failed) before the fix.
- Not changed: `scripts/qa/dangerous-invocation-corpus.yaml` has no rows for
  any scratch guard (only the typed-phrase gates), so no row added.
  `docs/guides/HANDLER_REFERENCE.md` and the module docstring already describe
  the fail-closed behaviour; release note 021 does not state the old behaviour.

## Unit 2: truth-changes manifest missed by 3.76.0

- `git mv` `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.76.0.yaml` ->
  `v3.77.0.yaml`, `version: "3.77.0"` (the name/version tie is asserted by
  `tests/integration/test_unreleased_truth_changes_manifests.py`).
- The README there names no version; nothing to change. The one path
  reference, in `CLAUDE/Plan/Completed/00621-.../PLAN.md`, now points at the
  new name. Released 3.76.0 notes untouched.

## QA

ruff, black --check --target-version py311, mypy on the touched source: clean.
pytest on the guard test file plus `tests/integration/test_no_root_conditioned_skips.py`:
all pass. Truth-changes tests: see the final reply.
