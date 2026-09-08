# Task 1.6 — `tdd_enforcement` accepts a nested MIRROR test root

**Branch**: `agent-ade94cba6e16a7921-ee16732b` (worktree
`/workspace/.claude/worktrees/agent-ade94cba6e16a7921-ee16732b`)
**Report section**: §6 (HIGH)

## What was wrong

`_get_test_file_paths` produced exactly the five candidates in the report's
deny output and nothing else: the built-in mirror hardcodes `tests/<mirror>`,
the package-stripping resolver hardcodes `tests/unit/`, `test_path_map` was
flat by contract, and `layout.test_dirs` only classified. A
`tests/Small/<mirror>` / `tests/Large/<mirror>` layout could only disable
the gate.

## What changed

`src/claude_code_hooks_daemon/handlers/pre_tool_use/tdd_enforcement.py`

- `DeclaredTestDir.mirror: bool = False`; `_parse_test_path_map` reads an
  optional `mirror` key (non-boolean -> warn + skip, like every other
  malformed entry).
- `_map_declared_test_paths`: a mirror entry yields
  `<workspace>/<test_dir>/<source dirs after the glob's literal root>/<TestName>`.
  The literal root is the glob's leading wildcard-free segments
  (`_glob_literal_root`: `src/**` -> `src`, `apps/app/src/**` ->
  `apps/app/src`, `**/Rules/**` -> nothing, so the whole workspace-relative
  path is mirrored). Uses the strategy's `compute_test_filename`, so it is
  language-neutral. A flat entry is byte-identical to before (pinned).
- New `_map_layout_mirror_paths`: every nested literal `layout.test_dirs`
  entry (contains `/`, no `*?[`) is a mirror root for a source that has a
  `src` segment or a bare declared `layout.source_dirs` name, anchored on the
  segments before it exactly as `_map_src_to_tests_mirror` is. Bare names and
  globs contribute nothing, so zero-config candidates are unchanged (pinned).
- Candidate order: declared map -> layout mirror roots -> inference. Neither
  declared source is gated by `test_locations`. Every candidate is listed in
  the deny message as before.
- `get_claude_md` no longer says `test_dir` is FLAT unconditionally; it
  documents `mirror: true` and the `layout.test_dirs` route.

Docs: `docs/guides/HANDLER_REFERENCE.md` (locations list, options row — also
drops a stale "(or absolute)", config example, malformed-entry sentence),
`config/models.py` `LayoutConfig.test_dirs` docstring + field description,
`CLAUDE/Code/WorkspaceResolution.md` anchoring note.

Release: `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-tdd-gate-accepts-nested-mirror-test-roots.md`
(Plan 00362, audience `client projects`) and
`CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.63.0.yaml` (new `mirror`
key; the version number is a guess for the release agent to correct).

## Tests (TDD: written first, 11 red -> all green)

`tests/unit/handlers/test_tdd_enforcement.py`: `TestMirrorTestPathMap`
(9 tests) and `TestLayoutTestDirsAsMirrorRoots` (6 tests), including the
requested pin `src/PackageType/OptimiseProbe.php` ->
`tests/Small/PackageType/OptimiseProbeTest.php` via `layout.test_dirs`
alone, both-roots-listed-in-deny, flat-contract-unchanged, and
zero-config-unchanged.

Verification: `tests/unit/handlers/test_tdd_enforcement.py`,
`tests/unit/utils/test_path_exclusion.py`, `tests/unit/config` all pass
(469); `ruff check`/`ruff format` clean; `mypy --strict` clean on the two
source files. Daemon NOT restarted (per instruction; the CLAUDE.md
`<hooksdaemon>` block regenerates on the next restart).

## Environment note

`scripts/setup_worktree.sh` creates a NEW worktree and refuses to run inside
one, so the venv here was built with the same steps it performs
(`uv sync --frozen --extra dev`) into `untracked/venv-wt/`. `--frozen`
without `--extra dev` omits pytest.

## Not done / for the coordinator

- PLAN.md Task 1.6 checkbox left for the coordinator (avoids a conflict
  with other Phase-1 agents on the same file).
- The JOURNAL day-file received one entry; other agents append to the same
  file, so expect a trivial merge.
