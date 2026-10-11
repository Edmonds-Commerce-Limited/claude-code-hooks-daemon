# Batch AL report (Sonnet): N411, N402 (b), N419

Branch `worktree-batch-al-guards`. Tests were written first for each item; RED output is quoted below.

## N411, option A: auto-continue stands down when it cannot read the transcript

- `src/claude_code_hooks_daemon/utils/stop_hook_helpers.py`: new `transcript_is_readable(path)`. True only when the file opens. No path, a missing file, a directory or a permission error are all False. This is the piece that tells "cannot read" from "read it, no marker", which `has_recent_stop_hook_block` returns False for alike.
- `src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py`, `matches()`: on `stop_hook_active`, an unreadable transcript now returns False (allow the stop, log at info). Behaviour that stays as it was: a readable transcript with no marker, or with the marker more than 20 lines back, is still treated as a fresh stop (the Plan 00101 silent-stop recovery). Only "cannot read" changed.
- RED: `3 failed, 180 passed` in `test_auto_continue_stop.py` (`assert True is False` for no path, missing file, and a directory as path); `test_stop_hook_helpers.py` failed at collection with `ImportError: cannot import name 'transcript_is_readable'`.
- The old test `test_matches_true_when_stop_hook_active_but_transcript_missing` pinned the opposite behaviour; it is replaced by four tests (no path, missing file, directory, and a fresh stop with `stop_hook_active` false unaffected).
- GREEN: stop handlers, stop helpers and the daemon-flow integration test, 354 passed.

## N402 part (b), option B: fail-closed kept, guidance added

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/conflict_marker_commit_gate.py`: `_REPHRASE` (appended to every "NOT checked" deny) now says `cd "$(git rev-parse --show-toplevel)" && git commit ...` is read and accepted, as are `cd "$PWD"` and `cd "$(pwd)"`, and that another variable (`cd $PROJ`) stays denied. No verdict changes.
- Which forms pass, checked by running them rather than from the write-up: the three above, QUOTED. The unquoted `cd $(pwd) && git commit` is DENIED today (my first test, with the unquoted form, failed with `Decision.DENY`). The write-up says "`$(pwd)`" without saying quoted; the existing placement tests only pin the quoted forms, so the guidance names the quoted ones. Whether unquoted `$(pwd)` should also pass is a separate verdict change, not made here. `cd $PWD` unquoted was not tested by me beyond the corpus; the guidance names only quoted forms.
- RED: `test_the_deny_names_the_forms_that_do_reach_the_project_root` failed (`assert 'cd "$(git rev-parse --show-toplevel)"' in 'BLOCKED [R-CONFLICT-MARK...`). A second test pins that each named form is allowed on a clean tree; it passes before and after the fix, as it should (it guards the guidance against drifting from the verdicts).
- GREEN: 211 passed (gate and invocation-directory tests).

## N419, option B: `ps` and `file` exempt; docker/podman exempt only before the image

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py`:
  - `ps` and `file` added to `_INLINE_CODE_FLAG_TEXT_TOOLS` (their `-e`, `-c`, `-r` are their own options).
  - docker and podman are NOT added to that set. A new `_container_args_after_image` reads `docker|podman run|exec|create`, walks past options (skipping the value of the options in `_CONTAINER_VALUE_OPTIONS`) to the first positional (the image or container), and returns the words after it. `_runs_inline_code` then judges only those words. So `docker run -e A=1 img cmd` is silent, while `docker run img perl -e ...`, `docker run -e A=1 img sh -c '...'` and `docker exec ctr sh -c ...` stay UNSEEN.
- Why this and not exempting docker outright: `docker run IMG sh -c 'pytest'` hands a program in the container inline code, and a plain exemption would make it invisible. Fail-closed direction of the one soft spot: an option the value list does not know has its value read as the image, which moves the boundary earlier and judges MORE words, never fewer. A global option before the subcommand (`docker --context x run -e ...`) and other subcommands (`docker build -e`) keep the generic rule. Pinned.
- Not decided here: a `-c` before the image is also exempt (docker's `--cpu-shares` is `-c`); nothing in the container can run code through it.
- RED: `11 failed, 67 passed` in the inline-flag classes (`ps -e`, `ps -e -o pid,comm`, `file -e/-c/-r`, and six docker/podman run/exec forms). The 9 after-image and unknown-shape rows already passed and pin the fail-closed side.
- GREEN: `2167 passed` across the handler's tests, the conflict gate tests and the false-positive corpora.
- Ledger consequence: of #69's commands, `ps -e`, `file -e` and `docker run -e A=1 img cmd` are now silent. The deny-list design (the option A the owner did not choose) is unchanged.

## QA

`./scripts/qa/llm_qa.py changed`: format, lint, type_check, pyright, error_hiding, docs_qa, magic_values and the rest pass. `changed_tests`: `5659 passed, 0 failed, 5 skipped`, but the run reports FAIL because `subagent_full_qa_blocker.py` maps to `[too-broad]` (unmapped file; the tool says to add a test, a map rule or `--allow-unmapped`). That is a property of the mapper and this file, not of this change; I ran that file's own test module directly (included in the 2167). `plan_qa` has one advisory, `journal-freshness` for plan 00495, unrelated to this batch.

The first QA attempt waited the full 600 s for the host-wide QA lock held by another worktree and did not start; the retry with `FULL_QA_LOCK_WAIT_SECONDS=1500` ran.

## Not touched

`.claude/ccy/`, settings files, the block-word list, the NIGGLES.md statuses (the brief did not ask for ledger edits; N411, N402 (b) and N419 still read Open there).
