# CI superlinear failure (ledger 00466 N106)

Branch `worktree-n466-superlinear`, fix commit `18273e79d` (off main
`4f0a205b3`). Gate queued in the background, not awaited.

## Verdict: the cost is in the code, not the measurement

CI run 36230375505 (main `8ea091652`) failed
`test_no_handler_grows_superlinearly_on_a_deep_write_path` on Python 3.12 and
3.13. The failing handlers were `ProjectContainmentHandler` (24x),
`PlanJournalGuardHandler` (26x) and `InstalledPluginEditAdvisorHandler`
(27-29x).

Evidence:

| Measurement (8x path depth, `scaling_ratio`)       | Python 3.11     | Python 3.13             |
| -------------------------------------------------- | --------------- | ----------------------- |
| The three handlers, 10-15 runs each (min/med/max)  | 7.6 / 8.8 / 9.7 | 25.2 / 33.9-42.7 / 51.0 |
| Bare `relative_to` + `is_relative_to`, 1000->8000  | 5.8             | 52.6 (3.12: 52.2)       |
| The three handlers after the fix, under contention | n/a             | 6.5 / 8.7-9.0 / 10.7    |

The last row was measured while an 8-core test run was going.

- cProfile at depth 8000 put almost all the time in `Sequence.__contains__`
  over `PurePath.parents`, called from `relative_to`/`is_relative_to`. Each
  handler reached it through a different site:
  `project_containment._is_within`, `worktree_paths.enclosing_checkout`, and
  the `installed_plugin_edit_advisor` genexpr.
- From 3.12 the stdlib implements both methods as `other in self.parents`.
  Every parent is a new path whose string is joined from all segments above
  it, so the cost is O(d^2). Python 3.11 compared `_parts` and is linear.
  That is why the local gate, whose venv is 3.11, passed.

## Fix

- `src/claude_code_hooks_daemon/utils/path_containment.py`:
  `path_is_relative_to` and `path_relative_to`. They read `parts` once and
  match the stdlib's answer, result type and ValueError, including the edge
  cases for `.`, anchors and Windows case.
- All 126 stdlib sites in `src/` and `scripts/` now use it. `scan_scope.py`
  must stay stdlib-only, so it compares `parts` inline.
- The detector is `scripts/qa/semgrep/pathlib-quadratic-containment.yaml`. It
  bans `.relative_to(`, `.is_relative_to(` and `in`/`not in X.parents`, with
  no exclusions. It is pinned by `tests/fixtures/semgrep/pathlib_quadratic_containment.py`
  (7 hits, 5 clean) and `tests/unit/qa/test_semgrep_pathlib_quadratic_containment.py`.
  `run_semgrep_check.sh` reports 0 violations over the tree.
- A second instance turned up once the deep-path sweep also wrote `.md`.
  `markdown_organization._is_plugin_component` probed every ancestor for a
  plugin manifest. Each probe past PATH_MAX fails and is logged with the
  whole path, giving 122x for 8x depth and 15s per call at 16 KB. It now
  walks down from the workspace root and stops at the first directory that
  does not exist, so the nearest root still wins. The sweep is now
  parametrised over `.py .md .sh .ts .json`, because the `.py`-only sweep
  had hidden this case.

## RED proofs

All were run on a `git archive` scratch copy of main.

- `tests/unit/utils/test_path_containment.py` counts the segments the helper
  reads through `parts`/`str` on a counting `PurePosixPath` subclass. That
  is deterministic and independent of the Python version. With the helper
  swapped for the stdlib, 3.13 counts 63x and both growth tests FAIL. The
  helper counts 8x. A parent-walk reference counts more than 24x, which
  proves the count can see a quadratic.
- In `test_markdown_organization.py`,
  `test_a_deep_path_probes_only_directories_that_exist` counts 103 vs 803
  probes on main (FAIL) and equal counts on the fix. The new
  `test_the_nearest_plugin_root_decides` passes on both, so the walk
  direction did not change behaviour.

## Verification

- `tests/unit/{handlers,utils,core,qa,scripts,block_report,daemon,docs_qa,install,issue_report,plan_qa,reference_repos,remote_docs,tool_report}`
  plus `test_plan_finder.py` and `test_plan_links.py`: 21064 passed, 0
  failed. The 3 `test_run_dependency_check` failures in an earlier run came
  from my own venv, built with `uv pip install -e .[dev]` and so off the
  lock. It was re-synced with `uv sync --frozen --all-extras`, and they pass.
- ruff, black (the locked 26.3.1), mypy and pyright are clean on all 76
  touched Python files.
- The worktree daemon restarted and reports RUNNING.
- Ledger: an N106 entry in NIGGLES.md and a PLAN.md row marked Remedied.
  Release note 98 is included because the `.md` stall was user-visible.

The 126-site migration was split across four Sonnet subagents on disjoint
file lists, then reviewed. The three flagged handlers, `core/` and the
markdown walk were reviewed line by line.
