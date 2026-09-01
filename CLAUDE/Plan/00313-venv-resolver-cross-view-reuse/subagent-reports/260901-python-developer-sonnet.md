# Plan 00313 Phase 1 — venv resolver cross-view reuse fix

**Agent**: python-developer (Sonnet)
**Scope**: Tasks 1.1–1.4 (TDD fix, bash parity check, full QA)

## What changed

### `src/claude_code_hooks_daemon/daemon/paths.py`

- Added `_VENV_NAME_SLUG_PATTERN` (a regex anchored on the interpreter
  fingerprint tail `-py\d+-[a-f0-9]+` so it parses a `venv-*` directory name
  from the RIGHT — the slug itself may contain hyphens).
- Added `_parse_venv_dir_slug(venv_dir_name)` — returns the embedded
  project-root slug, or `None` for a legacy un-slugged name
  (`venv-py311-<hex>`).
- Added `_venv_slug_eligible(venv_dir, current_slug)` — the shared
  eligibility helper. Returns `(True, None)` when the venv's slug matches
  `current_slug` or has no slug (legacy); otherwise `(False, "skipped <name>: slug '<x>' does not match current root slug '<y>'")`.
- Applied the helper:
  - `resolve_existing_venv_python` step 3 (scan fallback): skips
    slug-ineligible candidates before the executable check.
  - `resolve_existing_venv_python_with_diagnostics` step 2 (metadata):
    skips slug-ineligible candidates before reading `.daemon-metadata.json`
    at all (so a lock_hash match on a mismatched-slug venv never surfaces).
    Skip reasons are collected and logged as a single `step 2: ...` line
    when no other match is found.
  - Same function's step 4 (scan fallback): same treatment, logged as
    `step 4: ...`.
- The fingerprint-keyed steps (step 2 of the simple resolver, step 3 of the
  diagnostics resolver) needed **no change** —
  `python_venv_fingerprint(daemon_path)` already embeds the slug via
  `project_path_slug()`, so a mismatched root's exact-fingerprint lookup
  simply misses on its own.

### Tests (RED first, then GREEN)

- `tests/unit/daemon/test_paths_resolve_existing_venv.py`: new
  `TestScanFallbackSlugEligibility` class, 5 tests — slug-mismatched venv
  skipped by scan, slug-matched venv resolved, legacy un-slugged venv still
  resolved, and the hostname-suffixed variant of the first two.
- `tests/unit/daemon/test_paths_resolve_venv_diagnostics.py`: new
  `TestSlugEligibility` class, 7 tests — metadata step skips a
  lock_hash-matching venv whose slug mismatches (even with a valid
  `python_path`) and resolves a slug-matched one; scan fallback skips
  mismatched/resolves matched/still resolves legacy un-slugged, plus the
  hostname-suffixed variants.
- Confirmed RED (5 failures, exactly the mismatch-skip cases) before
  implementing; GREEN after — 64/64 passed in both files.

## Task 1.3 — bash parity

No separate fix needed; documented in the journal
(`JOURNAL/00313-Journal-26-09-01.md`, 20:57 entry). Both
`scripts/lib/resolve_venv.sh` and
`src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh`
shell out to `paths.py resolve-venv` (the Python SSOT) for the actual
resolution answer. `_rv_pick_python`'s own `venv-*` glob in
`resolve_venv.sh` only selects *which interpreter to invoke `paths.py`
with* — the value returned to every caller is `paths.py`'s stdout, which is
the now-fixed SSOT. Even a slug-mismatched venv's `bin/python` is safe to
use for that bootstrap purpose since `paths.py` only needs 3.11+ stdlib to
run and computes its own (slug-aware) answer independently.
`_resolve-venv.sh` sources `resolve_venv.sh` directly and inherits the fix
transitively.

## Test results

- `tests/unit/daemon/test_paths_resolve_existing_venv.py` +
  `tests/unit/daemon/test_paths_resolve_venv_diagnostics.py`: **64 passed**.
- `tests/unit/daemon/` (full): **1444 passed, 1 skipped** (pre-existing
  root-context skip, unrelated).
- Integration venv-resolver suites (`test_paths_resolve_venv_cli.py`,
  `test_venv_resolver_parity_matrix.py`,
  `test_venv_resolver_multi_host_nfs_fail_fast.py`,
  `test_venv_resolver_pipefail_cascade.py`, `test_install_venv_resolver.py`,
  `test_paths_resolve_venv_under_any_python.py`): **23 passed**.
- `mypy --strict` on `paths.py`: clean.

## Full QA

`./scripts/qa/llm_qa.py all`: **25/25 PASSED** (17,163 tests, 0 failed, 7
skipped, 95.2% coverage). Note for future runs in this repo: the `format`
gate (`scripts/qa/run_format_check.sh`) checks with **`black`**, not `ruff format` — the two formatters disagree on how to wrap a multi-line `assert cond, f"message"` statement. An interactive `ruff format` pass on a touched
file is not sufficient to satisfy this gate; run `black` (via
`scripts/venv-include.bash`'s `venv_tool black <files>`) or the QA script
itself before treating formatting as settled.

## Docs updated

- `CLAUDE/Plan/00313-venv-resolver-cross-view-reuse/PLAN.md`: Task 1.1–1.4
  checkboxes ticked. **Success Criteria left unchecked** — `plan_qa_edit`
  blocks ticking them while `**Status**: In Progress` stands (a
  header/body-coherence check), and flipping status + archiving is the
  release coordinator's call, not this dispatch's.
- `CHANGELOG.md` `## [3.59.0]` → `### Fixed`: new entry describing the
  defect and fix.
- `RELEASES/v3.59.0.md`: Summary, Highlights, and `### Fixed` updated to
  match.

## For coordinator attention

- No commit made, per dispatch instructions.
- PLAN.md Success Criteria checkboxes and the `**Status**` header are still
  pending — flip both and archive per the Plan Completion Checklist when
  ready to close this plan.
