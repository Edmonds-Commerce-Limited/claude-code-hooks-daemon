# Plan 00640: review fixes for PR 255

Branch `fix-ccy-dockerfile-arm64-dart`. Step 0: `git merge --no-ff origin/main` merged cleanly. The README "Active: 90" count was checked and matches the 90 root plan folders.

## Done

- **S1**: `branch_inventory.py` and `branch_creation.py` now use `park_covers_tip`. Tests were written first and were red: 2 failed, 37 passed. The tests are in `tests/unit/core/test_branch_park_no_commit.py` and `tests/unit/core/test_branch_park_gaps.py`. One existing test asserted the old behaviour (new work returns the branch to open) and was flipped to match.
- **S2** (decision): a park whose tip is still the parked commit is deliberately not ended by age. The parked pool already reports such a park as STALE past `max_age_days` (`branch-sweep`, the creation guard). Ending the record would hide that signal. Only the follow case (later commits on top) is bounded by `max_age_days`. The docstrings of `park_covers_tip` and `announce_ended_parks`, release note 107 and PLAN.md say so. `TestParkCoversTip` pins it.
- **S3**: no code narrowing. Docstring, release note 107 and PLAN.md say the rule applies to every park, that a push ends nothing, and that the follow is bounded by `max_age_days`.
- **S5**: the four docstrings and guidance strings are updated, and the mixed-findings deny line now says "abandoned (or as left unpushed where unpushed commits are a branch's only finding)". The repo `CLAUDE.md` carries no copy of that text, so nothing generated was edited.
- **S6**: the README row for 00640 is now In Progress.
- **Plan text**: Goals, Task 2.3, the last success criterion and Delivery now match the code. The archive move is after the merge, not in this PR.
- **Dockerfile**: `gnupg` and `apt-transport-https` removed. Nothing else in the file uses them. The Dart zip is still `latest` with no checksum or pin: no web-fetch tool was available to verify a pinned version or sha256, so I added nothing unverified.
- **S4**: cannot be repaired retroactively (reproduction tests and fix landed together in `c5c29e2d6` and `1bf547492`). Said so in the plan journal entry `JOURNAL/2026-11-25/135853Z-action-b5478d.md`.

## BLOCKER: not fixed as asked

I did not add `changed_tests_map.yaml` rules. `CLAUDE/QA.md` ("The Unmapped and Too-Broad Fallback") says a rule adds tests but never clears `too-broad`. The `run_changed_tests.py` code agrees: the too-broad reason is set before declared rules can matter. `.github/workflows/qa.yml` already handles this case: with unmapped files it leaves `changed_tests` out and runs the whole suite in the `fallback-tests` job, otherwise it uses `--allow-unmapped`.

I could not read the CI job log for run 45624905569, because the run was still in progress. Its failing step was "Targeted QA (code tier)", so the real cause is unconfirmed. I ran every `changed` tool except `changed_tests` locally (the same list CI runs in that step), on the tree before the final commit:

- 15 of 17 passed.
- `semgrep` errored: `uv` is not installed in this sandbox, so it could not run here.
- `project_handlers` ran 301 passed but is marked NOT MEANINGFUL because `semgrep` failed.

If CI's `uv` is present, `semgrep` is not the cause; the cause remains unknown until the log of the new run is readable.

## `llm_qa.py changed` on the final tree

I ran `llm_qa.py changed` on HEAD `584c91e69`, a clean tree. My first attempt never started: another agent held the host-wide QA lock for the whole 600 s wait. The second attempt, with `FULL_QA_LOCK_WAIT_SECONDS=3000`, produced the following. The summary line is `QA: 40/43 PASSED, 2/43 FAILED, 1/43 NOT MEANINGFUL (detector failed: semgrep)`.

- **`semgrep`**: tool error, `uv` not found. This is an environment gap.
- **`changed_tests`**: 5838 passed, 24 failed, 9 skipped, and 5 unmapped files (all `[too-broad]`): `core/branch_creation.py`, `core/branch_inventory.py`, `core/branch_park.py`, `daemon/cli.py` and `handlers/session_start/branch_sweep.py`. The first two are new, because they now import `park_covers_tip`.
- **The 24 failures** include 14 in `tests/unit/qa/test_llm_qa_main_moved.py` and 1 in `tests/unit/core/test_empty_commit_proof.py` that the summary names; the other 9 are listed only in `changed_tests.json`, which I did not read. I re-ran both files with `-x` and the first failure is the `test_llm_qa_main_moved.py` case `test_a_document_nothing_reads_is_docs_only`. It fails with `VenvResolutionError: no QA interpreter for <this worktree>`, because this worktree has no venv of its own. I did not diagnose the `test_empty_commit_proof.py` failure; it is a different test and may or may not have the same cause. None of the failing tests touch the files I changed. I did not run them on `main` to prove they fail there too.
- **Everything else** passed, including `docs_qa`, `plan_qa`, `doc_truth`, `generated_doc_drift`, `handler_reference`, `inline_suppressions`, `released_changelog`, `pyright`, `type_check` and `format`.

## Targeted checks I ran

All commands ran from the worktree with `PYTHONPATH=<worktree>/src`, because the shared venv's editable install points at main's `src`.

- `pytest -p no:cacheprovider --no-cov -q tests/unit/core/test_branch_park_no_commit.py tests/unit/core/test_branch_park_gaps.py tests/unit/core/test_branch_inventory.py tests/unit/core/test_branch_creation.py tests/unit/core/test_branch_pools.py tests/unit/core/test_branch_stop_guard.py tests/unit/core/test_branch_park.py`: 304 passed.
- `pytest` on `tests/unit/core/test_branch_stop_gate.py`, `tests/unit/core/test_branch_stop_guard.py`, `tests/unit/handlers/stop`, `tests/unit/handlers/session_start/test_branch_sweep.py`, `tests/unit/daemon/test_cli_branch_sweep.py`, `tests/unit/daemon/test_cli_branch_park.py` and `tests/integration/test_claude_md_guidance_coverage.py`: 1371 passed, 1 xfailed.
- `black --target-version py311`, `ruff check` and `mypy` on the 8 changed Python files: all clean.
- No QA suppressions were added.

## Not done

- No amd64 build of the Dockerfile (S7), and no Dart pin or checksum.
- The CI failure cause is not confirmed.
- I did not diagnose the 24 `changed_tests` failures beyond the venv cause above.
