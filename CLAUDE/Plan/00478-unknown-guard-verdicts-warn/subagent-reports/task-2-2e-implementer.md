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

## Review fixes

Review: `task-2-2e-review-code-reviewer.md` (committed d90c8e96c). Each fix is test-first: the regression tests were run RED on f1a8f6d8b before the source change.

- **C1 (an unknown pipe launders a later blacklisted one).** RED: `test_pipe_blocker_unknown_verdict.py::TestAnUnknownPipeNeverLaundersADeniedOne` (7 compound commands across `&&`, `;`, `||`, newline, `$( )` and a loop closer, plus naming tests; 9 RED). Fix 45b7825a4: handle() judges every offending pipe (`_offending_matches`, `_denying_verdict`). The first prose, closer or blacklisted pipe denies and names its own producer. Only an all-unknown command gets the advisory, which names each producer.
- **C2 (wrapped blacklisted producers allowed).** RED: `TestAWrappedBlacklistedProducerStillDenies::test_denied` (22 spellings: env, `VAR=x`, timeout, sudo, nice, nohup, `bash`/`sh -c`, `uv run`, poetry, pipenv, npx, xargs, `python3 -m`, `.venv/bin/pytest`, `node_modules/.bin/jest`) and `test_pipe_blocker_wrapper_commands.py::test_a_wrapped_expensive_command_is_denied` (4); 26 RED. Fix 45b7825a4: `_run_targets` peels assignments, the shared `COMMAND_WRAPPERS`, `_RUNNERS`, `python -m` and `-c` bodies, and reduces the command word to its basename. The blacklist and `extra_blacklist` match every target, and the deny label names the wrapped command. `./scripts/qa/run_all.sh` is on no list, so it is unknown under the ruling; this project's `.claude/hooks-daemon.yaml` names `run_all.sh`/`run_tests.sh` in `extra_blacklist`, pinned by `test_a_configured_blacklist_entry_matches_the_script_at_any_path`. The reviewer probe builds a handler with no config, so it still reports that one case as allow; the other 15 deny.
- **C3 (awk writing to FILENAME over a named protected file).** RED: `test_write_protected_paths.py::TestAPathNobodyNamedWarnsInsteadOfDenying::test_an_awk_program_whose_file_operand_names_the_directory_is_denied` (4) and `test_an_awk_program_rewriting_a_named_protected_file_is_denied` (2); 6 RED. Fix 4ea2b656e: an awk program with a computed destination has its file operands judged through `_operand_naming` (roots and cd), and a named listed path denies. This also closes the literal-file-glob case, which was nomatch at base. Reviewer probe: 27/27 deny.
- **I1 (matches()-only pins).** C1/C2 tests above are handle()-level. Fix 21ddeec3b adds handle() DENY twins in the shell -c, reserved-word, literal-pipe and message-substitution suites.
- **I2 (overstated docs).** Fix 73d561a77: release note 031, `docs/guides/HANDLER_REFERENCE.md` (pipe_blocker and write_protected_paths) and both handlers' `get_claude_md` guidance now state the wrapper/runner coverage, every-pipe judging, the `extra_blacklist` route for an expensive command on no list, and the awk operand deny.
- **Minor.** The `_find_offending_producer` docstring now describes the empty producer as unknown-tier. The comprehensive `TestPipeBlockerHandleUnknown`/message-differentiation fixtures use `mytool` (not the whitelisted `find`) and assert `matches()` first (45b7825a4). The prose corpus now expects the venv `python3 -m pytest` command to deny as expensive; the branch had pinned it as allow, an instance of C2.
- Results (round 1): targeted pytest on all 14 test files touched since 6bba54cc7: 1514 passed. `run_autofix.sh` rc 0; mypy clean on both handlers; `config-validate` valid. `llm_qa.py changed` timed out waiting on the host-wide QA lock (held by pid 58368 in this worktree, likely the earlier background run), so it was not run.

## Review round 2 fixes

Review: `task-2-2e-rereview-code-reviewer.md` (committed af5607bad). Every fix was written test-first and its tests were run RED before the source change.

- **Structural rule (C-1, I-1, I-2).** At base, the unknown tier denied. That made it the net for every pipe whose blacklisted producer the parser could not place, and adding wrappers to a list will never cover them all.
  - The rule now: before an unknown-tier pipe may allow, `_blacklisted_word_anywhere` scans the whole inert-stripped command for a blacklisted producer, including `extra_blacklist`. That covers every segment, substitution, `-c` body and here-string.
  - Each word is checked three ways: as written, as its path basename, and with a glued `-m` removed. It is joined to the next 4 words, so multi-word patterns (`npm test`) still match. Matching is by whole word only, so `pytester` does not count.
  - A hit denies with the blacklisted reason. The reason names the command and adds a note that the guard could not tell which pipe it feeds (`_unplaced_verdict`).
  - A single `&` now separates statements in `_extract_producer` (`_last_background_statement`). Redirect forms are not split: `2>&1`, `>&2`, `&>`, `|&`.
  - The wrapper unwrapping stays in place for better reasons, but safety no longer depends on it.
  - Tests: `test_pipe_blocker_unplaced_producer.py`, 38 RED at first. It covers:
    - the 4 `&` cases, pinned as placed directly (no unplaced note);
    - the 20 I-1 shapes, plus `bash <<<` and `timeout 5s --`;
    - the 8 QA-script spellings, using the repo yaml;
    - `.bak`/`.orig` non-matches;
    - negative allows: `docker ps`, `mytool`, `systemctl`, `uv run my_report`, `timeout 5 docker ps`.
  - Commit: aa0631d4a.
- **Config.** `extra_blacklist` gains `'^llm_qa\.py(\s|$)'`. Base treated `python3 scripts/qa/llm_qa.py ... | tail` as unknown, so it denied there. All three entries now end in `(\s|$)` instead of `\b`, so `run_all.sh.bak` no longer matches.
- **Two pins changed to the base verdict.**
  - `docker run ... --entrypoint /bin/bash ... -lc make | head` now denies, because it runs `make`.
  - The `bash -c 'pytest | grep FAIL'` warn pin became `bash -c 'docker ps | grep Up'`. The pytest form now denies.
- **I-3.** The awk operand check now runs only when `_awk_destination_computed` is true: FILENAME, `$N`, a variable, `| cmd`, `system()`, or a non-literal `cmd | getline`. A program that writes only to string literals is judged by its text, as at base. Commit: 250a03cea.
- **I-4.** An operand containing `$`, a backtick or `~` that `_operand_naming` cannot resolve is judged by its text (`_unresolved_operand_naming`). A name or directory pattern match counts. A glob with no literal part (`**`) always counts, as at base.
- **M-1.** A writing awk program whose working directory is inside a listed wildcard-only directory glob denies (`_listed_directory_holding`). This covers `cd protected && ...` and a cwd inside `protected/`.
- **Classifier pins.** `test_which_awk_programs_compute_their_destination` has 11 cases.
- **M-2.** Release note 031, `HANDLER_REFERENCE.md` (both handlers), both `get_claude_md` texts and the yaml comment now state the whole-command scan rule and the awk split. Commit: 7ec427352.
- **Harness.** `untracked/scratch/rr2e/r2run.py` and `r2cmp.py` ran on a fresh detached checkout of 6bba54cc7 and on HEAD. That is 147 pipe cases (`cases.txt`, `cases-round3.txt`, the `base2.out` commands, `hd*.txt`) and 212 wpp case×glob rows. Output: `r3-cmp.txt`.
  - **Base deny, HEAD allow, pipe, with the repo config: 19.** All are unknown producers with no blacklisted word: `docker ps`, `mytool`, wrapped whitelisted readers such as `env grep`/`sudo cat`, `python -m http.server`, `python3 script.py`, `run_all.sh.bak`, and a trailing `&`. Without config the count is 29; the extra 10 are the QA-script spellings that the config covers.
  - **Base deny, HEAD allow, wpp: 59.**
    - 58 name no protected path under the glob in force. These are a `.claude/ccy/*` glob with `protected/x` operands, literal-destination awk reading a file, `other/` operands, and unreadable or brace-overflow text under `**`.
    - 1 is open: `${PWD}/protected/x` under `protected/**`. The shared word scanner stops at a `${...}` extent, so the operand never reaches the awk check.
  - **Base no-deny, HEAD deny: 10.** One is `echo hi & pytest | tail`, which pipes pytest. Eight are awk programs rewriting the named literal-glob file through FILENAME; that change was made in round 1 by C3.
- **Results.**
  - Targeted pytest over all 19 files (every test file changed since 6bba54cc7, plus all `test_pipe_blocker*.py` and `test_write_protected_paths*.py`): 1652 passed.
  - `run_autofix.sh`: rc 0, with one black reformat.
  - mypy: clean on both handlers.
- **Open.** `${PWD}/…` as an awk operand under a directory glob (see above).
