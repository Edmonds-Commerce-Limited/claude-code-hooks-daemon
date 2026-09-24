# Plan 00458 Phase 1 implementation report

**Agent**: python-developer subagent (Sonnet 5)
**Scope**: Task 1.1 (audit), 1.2 (detector, RED), 1.3 (shared matcher, GREEN), 1.4 (security doc + release note)
**Worktree**: `worktree-plan-458-skip-paths`, branch `worktree-plan-458-skip-paths`

## Task 1.1 — Audit

Confirmed the six named sites and searched `src/claude_code_hooks_daemon` for
every `in file_path`/`in path`-shaped test, `startswith`/`endswith` against a
directory list.

| Site                                                                                                           | Shape                                                                                | In scope?               | Disposition                                                                                                                                                                                                                                                                                                                           |
| -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `handlers/pre_tool_use/qa_suppression.py:162`                                                                  | `any(skip_dir in file_path for skip_dir in strategy.skip_directories)`               | Yes                     | Fixed                                                                                                                                                                                                                                                                                                                                 |
| `handlers/pre_tool_use/comment_changelog.py:316`                                                               | same                                                                                 | Yes                     | Fixed                                                                                                                                                                                                                                                                                                                                 |
| `handlers/pre_tool_use/comment_size.py:280`                                                                    | same                                                                                 | Yes                     | Fixed                                                                                                                                                                                                                                                                                                                                 |
| `strategies/security/common.py:23`                                                                             | `any(skip in file_path for skip in SKIP_PATTERNS)`                                   | Yes                     | Fixed                                                                                                                                                                                                                                                                                                                                 |
| `strategies/tdd/common.py:14`                                                                                  | `any(test_dir in file_path for test_dir in COMMON_TEST_DIRECTORIES)`                 | Yes                     | Fixed                                                                                                                                                                                                                                                                                                                                 |
| `handlers/pre_tool_use/british_english.py:108`                                                                 | `any(dir in file_path for dir in self.CHECK_DIRECTORIES)`                            | Yes                     | Fixed                                                                                                                                                                                                                                                                                                                                 |
| `strategies/tdd/common.py:26` (`matches_directory`)                                                            | `for directory in directories: pattern = f"/{directory}/"; if pattern in file_path`  | Found, **out of scope** | Already both-side segment-bounded by construction (builds its own `/…/`); only the project-relativity half is missing. Fan-out is ~22 call sites across 11 per-language TDD strategies with no existing regression coverage for the venv-style collision — larger blast radius than this plan scoped. Left as a documented follow-up. |
| `handlers/post_tool_use/validate_eslint_on_write.py:328-331` (`is_worktree`)                                   | `any(f"{prefix}/" in file_path for prefix in (WORKTREES_DIR, CLAUDE_WORKTREES_DIR))` | Found, **out of scope** | Result feeds only a log line ("Detected worktree file..."), never a skip/gating decision — no behavioural fail-open.                                                                                                                                                                                                                  |
| `daemon_docs_guard.py:67`, `plan_qa_edit.py:117`, `plan_time_estimates.py:117`, `markdown_organization.py:902` | single FIXED, already both-side-slash-bounded pattern (`f"/{x}/"`)                   | Found, **out of scope** | Not a directory LIST — a narrower, different shape than this plan's "skip-list and directory-classification site" scope.                                                                                                                                                                                                              |

Full narrative: JOURNAL `11:22`.

## Task 1.2 — Detector (Defence Before Fix)

`scripts/qa/check_skip_list_substring.py` (rule id `unbounded-skip-list-membership`):
an AST detector that flags a comprehension's (or an explicit `for`'s) own
loop variable compared **unchanged**, via bare `in`, against something whose
identifier looks like a path (`file_path`, `abs_path`, `…_path`). Handles
both the `any(x in file_path for x in LIST)` comprehension shape and the
explicit `for x in LIST: if x in file_path:` variant named in the spec.

Deliberately stays quiet on:

- A reassigned/normalised loop variable (`tdd/common.py`'s `matches_directory`
  binds `pattern`, not the raw `directory`) — a different binding, not the
  hazard.
- An f-string-wrapped loop variable (`validate_eslint_on_write.py`'s
  `f"{prefix}/" in file_path`) — not a bare `Name`.
- An unrelated `in` test whose right-hand side doesn't look like a path
  (`any(k in content for k in KEYWORDS)`).
- A single fixed literal against a path (no list at all).

RED evidence (commit `d693e13c`): fired on exactly the six named sites, no
false positives:

```
Found 6 unbounded skip-list membership test(s):
  src/claude_code_hooks_daemon/handlers/pre_tool_use/british_english.py:108
  src/claude_code_hooks_daemon/handlers/pre_tool_use/comment_changelog.py:316
  src/claude_code_hooks_daemon/handlers/pre_tool_use/comment_size.py:280
  src/claude_code_hooks_daemon/handlers/pre_tool_use/qa_suppression.py:162
  src/claude_code_hooks_daemon/strategies/security/common.py:23
  src/claude_code_hooks_daemon/strategies/tdd/common.py:14
```

14 unit tests of the detector itself (`tests/unit/scripts/test_skip_list_substring_checker.py`),
including one that runs the detector against this repository's own source
tree as the fix's acceptance criterion. Registered in `scripts/qa/llm_qa.py`
(tool `skip_list_substring`) and `scripts/qa/run_all.sh` (step 30, plus the
summary table).

## Task 1.3 — Shared matcher, all sites moved

`src/claude_code_hooks_daemon/utils/path_segments.py::matches_path_segment`
(commit `25c4573e`): the one implementation now shared by every skip-list
site.

- **Segment-bounded**: a pattern must land at string-start or immediately
  after `/` — the fix `strategies/lint/common.py::matches_skip_path` already
  had, moved here. `matches_skip_path` is now a thin re-export (no
  `project_root` passed — unchanged behaviour; its own 33 tests stayed
  green).
- **Project-relative**: an optional `project_root` resolves `file_path`
  against it (via `os.path.relpath`) before matching. `project_root=None`
  (the default) preserves the old absolute-path behaviour, which is what
  keeps every pre-existing unit test for the six handlers passing unchanged
  (they construct handlers directly, with `ProjectContext` uninitialised).
- **Outside-project decision (spec point 2)**: a `file_path` that resolves
  outside `project_root` (or equals it) returns `False` — "not skipped" —
  because every one of the six sites is a guard where skipping means "stand
  down"; fail-closed is the safe default. Reused
  `utils.path_exclusion.resolve_project_root()` (best-effort, `None` when
  `ProjectContext` is uninitialised) as the project-root source, matching the
  existing `handler_excludes_path` idiom rather than inventing a second one.

All six sites moved (commit `ebb31e61`):

| Site                               | Before                                                                                                                     | After                                                                                                                               |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `qa_suppression.py:162`            | `any(skip_dir in file_path for skip_dir in strategy.skip_directories)`                                                     | `matches_path_segment(file_path, strategy.skip_directories, project_root=resolve_project_root())`                                   |
| `comment_changelog.py:316`         | same shape                                                                                                                 | same fix                                                                                                                            |
| `comment_size.py:280`              | same shape                                                                                                                 | same fix                                                                                                                            |
| `british_english.py:108`           | `any(dir in file_path for dir in self.CHECK_DIRECTORIES)` — `CHECK_DIRECTORIES` entries carry **no** trailing slash at all | patterns built as `f"{d}/"` at the call site, then `matches_path_segment(...)`                                                      |
| `strategies/security/common.py:23` | `any(skip in file_path for skip in SKIP_PATTERNS)`, `SKIP_PATTERNS` had **leading** slashes (`"/vendor/"`, …)              | leading slashes stripped (a leading slash never lands at the start of a relative path's first segment); `matches_path_segment(...)` |
| `strategies/tdd/common.py:14`      | `any(test_dir in file_path for test_dir in COMMON_TEST_DIRECTORIES)`, same leading-slash issue                             | same fix, same stripping                                                                                                            |

Per-site tests added (all use the `pc.ProjectContext` monkeypatch idiom from
`tests/unit/utils/test_path_exclusion.py::TestResolveProjectRoot`):

- A directory merely ending in the skip/check name (`myvendor/`, `autodocs/`,
  `myvenv/`, `rebuild/`) is **not** matched.
- A genuine skip directory directly under the project root **is** matched
  once `project_root` is supplied.
- A project living under an ancestor directory sharing the skip name
  (`/home/dev/vendor/proj`) is **still guarded** — the skip name is outside
  the project-relative path.
- The literal 00422 N20 reproduction — a worktree named
  `worktree-issue-53-venv`, a write under
  `<root>/untracked/scratch/acceptance-test-*/` — no longer silently stands
  the guard down, for `QaSuppressionHandler`, `CommentChangelogHandler` and
  `CommentSizeHandler`.

`tests/unit/strategies/tdd/test_common.py::test_common_test_directories_has_expected_entries`
updated for the stripped-leading-slash convention (the only pre-existing
test asserting the old literal form).

**Addendum, per review feedback**: the initial per-site tests above only
exercised `venv/`/`vendor/`/`docs/`/`tests/`, but the same bare-substring bug
applied identically to every OTHER entry of each list (`build/`, `dist/`,
`node_modules/`, `migrations/`, `tests/fixtures/`, `.env.example`, ...), and
a fix proven against one entry does not prove it against the rest. Added a
parametrized collision test (`x<entry>` — the entry string is present but not
segment-bounded — is not matched) and a positive test (the entry directly
under the project root is still matched) for **every entry of the list
actually in play** at each of the six sites, importing each list from its
source module (`PYTHON_QA_SUPPRESSION_SKIP_DIRECTORIES`,
`DEFAULT_SKIP_DIRECTORIES`, `SKIP_PATTERNS`, `COMMON_TEST_DIRECTORIES`, and
british_english's default `CHECK_DIRECTORIES` three) rather than
hand-duplicating the entries, so the tests stay in sync with the list itself.
80 new parametrized cases; 336 tests pass across the six touched files;
detector stays green (commit `6defb10a`).

## Task 1.4 — Security register + release note

`CLAUDE/Security/AsymmetricSiblingProtection.md`: new Instance "The worktree
that shared a suffix with a skip list", naming
`scripts/qa/check_skip_list_substring.py` as its Defence. Explicitly **no**
`declared-invariant-pairs` registry row — that registry's relations assert
agreement between two named symbols (a `reaches` row would prove the six
known sites call the shared matcher and say nothing about a seventh); the
class here is a *shape* that can recur with no sibling to compare against,
so a standalone AST detector covers it instead. Reasoning follows the
document's existing "why no row" precedent (the skills-rmtree and forwarder-
interpolation instances).

Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/08-skip-lists-now-match-whole-path-segments-relative-to-your-project.md`
(number 08; 06/07 reserved for parallel work per the team-lead spec).
Client-facing: states plainly that a client may see new blocks in
directories that were wrongly skipped before, and what to do about it.

## Final QA

Daemon in this worktree restarted (`./bin/hooks-daemon restart`) before each
QA run so acceptance probes actually execute rather than skip on a stale
source fingerprint. First run (daemon restarted before the Task 1.4 commit)
scored 34/36 — `smoke_test` and 21 `tests/acceptance/*` failed on a stale
source-fingerprint mismatch, not a real defect. Restarted the daemon again
after all commits landed and re-ran:

```
✅ tests: 25584 passed, 0 failed, 24 skipped | coverage: 95.1%
✅ smoke_test: 3/3 probes passed
QA: 36/36 PASSED
```

Confirmed the acceptance probes genuinely ran (not skipped) by running the
exact N20 regression test directly:

```
tests/acceptance/test_playbook_harness.py::TestTheDeclaredProbesBehaveAsDeclared
  ::test_every_executable_probe_matches_its_expected_decision_and_reason PASSED [13.52s]
```

After the every-skip-list-entry test addendum (commit `6defb10a`), daemon
restarted again and the suite re-run in full:

```
✅ tests: 25664 passed, 0 failed, 24 skipped | coverage: 95.1%
QA: 36/36 PASSED
```

## Out of scope / follow-up for the owner

- `strategies/tdd/common.py::matches_directory` (used by all 11 per-language
  TDD strategies' `_SOURCE_DIRECTORIES`/`_SKIP_DIRECTORIES`) still matches
  against the ABSOLUTE path — not project-relative. It is already segment-
  bounded, so it does not share the N20 substring-collision bug, but a
  project living under a directory named e.g. `src` would still be
  mis-classified. Converting it touches far more call sites than this plan
  scoped and has no existing regression coverage for that case.
- `handlers/post_tool_use/validate_eslint_on_write.py`'s `is_worktree` flag
  has the same bare-`in`-over-a-tuple shape but only feeds a log line.

## Commits (this worktree, unmerged)

- `d693e13c` — Task 1.2 detector, RED
- `25c4573e` — Task 1.3 shared matcher
- `ebb31e61` — Task 1.3 all six sites moved, GREEN
- `6defb10a` — every-skip-list-entry test addendum, per review feedback
- `4f8cac90` — Task 1.4 security doc instance + release note

Phase 1 (Tasks 1.1-1.4) complete; PLAN.md and the JOURNAL day-file are
updated. Phase 2 (merge, daemon restart in the main checkout, mark 00422 N20
remedied) is the team lead's.
