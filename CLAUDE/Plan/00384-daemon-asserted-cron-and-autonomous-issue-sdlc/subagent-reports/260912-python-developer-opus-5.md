# tdd_enforcement: uppercase `Tests/` is searched by the inferred resolvers

Issue 34 work, branch `worktree-issue-34-tests-dir-casing`. Nothing committed,
staged, merged or pushed — two modified files in the worktree:

- `/workspace/untracked/worktrees/worktree-issue-34-tests-dir-casing/src/claude_code_hooks_daemon/handlers/pre_tool_use/tdd_enforcement.py`
- `/workspace/untracked/worktrees/worktree-issue-34-tests-dir-casing/tests/unit/handlers/test_tdd_enforcement.py`

## The red test, and its exact failure output

Written first, before touching any source.
`tests/unit/handlers/test_tdd_enforcement.py::TestConventionalUppercaseTestsDirIsInferred`
— **4 failed, 3 passed in 0.31s**:

```
FAILED ...::test_an_uppercase_tests_sibling_satisfies_the_gate - AssertionError: assert <Decision.DENY: 'deny'> == 'allow'
FAILED ...::test_both_casings_are_named_in_the_deny_message - AssertionError: assert '/tmp/.../apps/app/qaConfig/Tests/CrossContextReadQueryWriteRuleTest.php' in 'BLOCKED [R-TDD-TEST-FIRST]: ...'
FAILED ...::test_an_uppercase_mirror_of_src_satisfies_the_gate - AssertionError: assert <Decision.DENY: 'deny'> == 'allow'
FAILED ...::test_an_uppercase_unit_subdir_satisfies_the_gate - AssertionError: assert <Decision.DENY: 'deny'> == 'allow'
```

The three that passed pre-fix are the invariants: lowercase still resolves, a
genuinely-missing test still denies, and `test_locations: [collocated]` still
suppresses the separate-style candidates.

The boundary tests were added next and pass both before and after, so they
characterise behaviour the fix must not change:

- `TestDeclaredTestPathMap::test_a_declared_test_dir_is_searched_only_in_the_casing_declared`
- `TestLayoutTestDirsAsMirrorRoots::test_a_nested_root_is_searched_only_in_the_casing_declared`

## What changed, and why there

`_INFERRED_TEST_DIRS = (_TEST_DIR, _TEST_DIR_UPPERCASE)` — the casing policy sits
in exactly one place, and the separate-style block in `_get_test_file_paths`
loops over it, as specified. Lowercase runs first, so the existing candidate
sequence is byte-identical and uppercase is strictly appended
(`test_layout_mirror_roots_rank_after_declared_map_before_inference` pins
indices 0-2 and still passes unchanged). `_map_declared_test_paths` and
`_map_layout_mirror_paths` are outside the loop and untouched.

**One deviation from the instruction, deliberate.** The three inferred mappers
were parametrised with `test_dir: str = _TEST_DIR` rather than rewriting their
finished `Path` at the assembly point. Post-hoc surgery cannot tell which
`tests` segment the resolver inserted: a repo checked out under a directory
literally named `tests` (`/srv/tests/myrepo/src/A/Foo.php`) would get the wrong
segment rewritten. Passing the name down is correct by construction, and the
*decision* — which casings, for which resolvers — still lives only at the
assembly point.

`_append_unique` was added and every candidate routed through it (the layout
block already did this inline). Needed because an uppercase variant can now
coincide with a declared `test_dir` — the reporter's own repo would hit this if
they kept their `test_path_map` — and a duplicated line in the deny message
reads as two places to look when there is one.

## Counts

- Handler file: **191 passed** (182 pre-existing + 9 added).
- `./scripts/qa/run_format_check.sh`: `✅ PASSED` after black auto-fixed my
  wrapping (first run reported 1 file reformatted, second run clean).
- `ruff check` clean and `mypy` clean on both changed files.
- Regression sweep, `tests/unit` + `tests/integration`: **12287 passed**,
  1 pre-existing failure (below).

The full QA suite was NOT run, per instruction.

## Things not described in the brief

**1. The casing fix alone resolves the field report with zero config.** The
fallback resolver walks a fixed three parents up; from
`qaConfig/PHPStan/Rules/<Rule>.php` that lands on `qaConfig/`, so
`qaConfig/Tests/<Rule>Test.php` is now found with no `test_path_map` at all.
The reporter never needed a declaration — they needed the other casing.

**2. That broke 10 existing tests, and the breakage was correct.** Nine in
`TestDeclaredTestPathMap`: that class uses the reporter's exact shallow layout
and treats "denied" as its proxy for "the mapping did not take" (absolute
`test_dir` rejected, unanchorable root, six malformed-config params, plus the
explicit `test_unconfigured_the_correctly_placed_test_is_not_found` baseline).
The proxy is only valid while inference cannot reach `qaConfig/Tests/` — i.e. it
was pinning the defect. The class's rules moved one directory deeper
(`Rules/Policy/`), which puts the fallback's fixed anchor on `qaConfig/PHPStan/`
and restores every test's original intent; the shallow reporter layout is now
pinned in the new class instead. **So "existing tests all still pass" was not
achievable as stated** — one of them asserted the bug.

The tenth is more interesting:
`TestDeclaredTestPathMapWorkspaceAnchoring::test_an_undeclared_subproject_still_anchors_at_the_repository_root`
is an anti-inference pin asserting `web/qaConfig/Tests` is absent from the
candidate list. The uppercase fallback now produces that path independently, so
the *assertion* became a false proxy while the *behaviour* it guards is
unchanged. It was re-pointed at `_map_declared_test_paths` directly, which is
the unit whose anchoring is under test and is immune to unrelated inferred
candidates.

**3. Pre-existing failure, not from this work.**
`tests/unit/install/test_reference_config_completeness.py::test_every_registered_handler_is_listed_for_its_event`
and
`tests/integration/test_example_config.py::test_example_config_includes_all_library_handlers`
both fail on `persistent_cron_assertor`. Commit `94851421` (Plan 00384 P1)
registered that handler in `handlers/session_start/__init__.py` and
`init_config.py` without adding it to the reference/example config YAMLs. This
diff touches two files, neither of which either test reads. Expect these in the
coordinator's QA run.

**4. Left alone deliberately:** `get_claude_md()`'s "Test file locations checked"
bullet list still names only `tests/...`. Adding a casing line is one sentence,
but that block is injected into every session (~18,300 tokens/session by this
repo's own measurement) and regenerating the tracked `CLAUDE.md` needs a daemon
restart the coordinator controls. The deny message — what a blocked agent
actually reads — names both casings, so nothing is silently unexplained. Owner's
call whether to spend the budget.

## Safety assessment

The change is not unsafe. It only lengthens the candidate list, and the gate
denies on an empty result, so it can remove a false block but cannot create a
false pass. The deny message lists every new location, so a reporter can still
see exactly where the gate looked.
