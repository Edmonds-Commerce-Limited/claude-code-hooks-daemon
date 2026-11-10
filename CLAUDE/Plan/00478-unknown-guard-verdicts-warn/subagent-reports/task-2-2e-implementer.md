# Task 2.2b / 2.2e implementer report (branch worktree-478-2e-contested-rows)

Commits since 6bba54cc7: afcda1796 (2.2b), f5e3b4c7d (row 16), e689a11b8 (row 26 source), 6eecb1ea2 (row 26 tests), plus the final commit (docs, release note, this report).

## 2.2b (row 2, test only)

- `tests/unit/handlers/pre_tool_use/test_destructive_git_force_removal.py:270` `TestSubstitutionIsNotTrusted` (branch and worktree twins). Passed immediately: pin test, behaviour unchanged (`_SUBSTITUTION` at `destructive_git.py:450`, used at :727 and :792).

## Row 16: write_protected_paths

Converted to warn (path not literally named in the command): `_text_naming` (src `write_protected_paths.py:749`, records a cause via `_note_unknown` :782 instead of returning a glob with no literal part), `_unread_naming` :776 (used by `_command_violation` :948 and `_rescanned` :1266), `_spelled_violation` :895 (brace cap), `_deep_violation` :1297 (depth/size except branch), `_reader_writes_violation` :1220 (awk computed destination). `_verdict` :847 returns (glob, cause); `handle` returns `unknown_verdict_allow` at :1408. Stale `_directory_pattern` docstring (:581) corrected in the final commit.
Tests: flipped `test_write_protected_paths.py:340` (RED seen: deny); new `TestAPathNobodyNamedWarnsInsteadOfDenying` :1636 (written with the flip, not individually watched RED).
Left as deny (a path or wildcard that can reach a listed path is positively present): `_token_naming` wildcard, `_wide_naming` words, find/xargs/read-loop, `_protecting_by_name`, unknown verb on a named path.

## Row 26: pipe_blocker

- Source `pipe_blocker.py:1077` `_unknown_producer_verdict`; `handle()` calls it at :1147, before the disclosure tracker is touched. Prose, compound-closer and blacklist denies unchanged. `_unknown_reason` / `_unknown_terse_reason` removed. Guidance updated: `_pipe_verbose_content` (:291), `get_claude_md` opening and whitelist paragraphs; `docs/guides/HANDLER_REFERENCE.md` pipe_blocker "Cannot decide"; `docs/guides/VERDICT_LOG.md` rule example.
- New `test_pipe_blocker_unknown_verdict.py`: 7 RED (deny) before the source change, 15 pass after.
- 56 old tests failed after the source change. All had a genuinely unknown producer (docker, find, mytool, mymodule, some_unknown_tool, a long git merge-tree / docker run corpus), so none was a regression. Converted in test_pipe_blocker.py (echd-capture cases to advisory assertions; the two unknown-message classes and the docker-ps deny row deleted because they only checked removed message text), test_pipe_blocker_comprehensive.py (HandleUnknown, Differentiation, PythonModuleLabel), test_pipe_blocker_prose_remediation.py, test_pipe_blocker_reserved_words.py, test_pipe_blocker_command_substitution.py, tests/integration/test_pipe_blocker_integration.py (footer test now uses blacklisted `cargo build`; docker ps test now asserts allow + advisory). Blacklisted assertions untouched.
- `kubectl annotate ... | head` is blacklisted (not unknown) and still denies; its test case now expects DENY with a non-prose reason.

## Results

- Targeted pytest on all 9 test files touched since 6bba54cc7: 951 passed.
- `run_autofix.sh`: rc 0 (it reformatted test_pipe_blocker_unknown_verdict.py).
- `llm_qa.py changed` (ran past the 600 s foreground limit, finished in background): found 3 failures + lint F811 + pyright, all mine and now fixed: (1) `test_pipe_blocker_integration.py` duplicate method name (my rename collided with an existing test; renamed `test_cargo_deny_has_single_disable_footer`); (2) pipe_blocker's own acceptance test "docker ps piped to tail" pinned the unknown deny (`pipe_blocker.py` get_acceptance_tests, now ADVISORY/ALLOW with `pipe_blocker`/`extra_whitelist` patterns; `test_acceptance_contract.py` two tests pass again); (3) `tests/unit/handlers/test_registry_option_injection.py::test_unparseable_pattern_is_not_fatal` now expects allow + advisory. Re-ran those files: 605 passed. `llm_qa.py changed` not re-run in full after the fixes (10 min); the coordinator's gate covers it.

## Ambiguities

- (a) awk computed-destination write with no literal mention converted to warn; arguably could stay deny.
- (b) pipe_blocker prose reason and compound-closer denies left as deny (also cannot-tell shaped, outside the brief).
- (c) wildcard tokens reaching a `**` glob stay deny.
- Release note 031 added; release-notes/README.md has no index rows for 027-030, so none added.
