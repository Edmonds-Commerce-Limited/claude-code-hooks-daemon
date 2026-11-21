# Plan 00627: handoff after ruling R7a and Task 2.3

Branch `agent-acff915e4bf3b86e6-0a26f829`, pushed, not merged. The previous handoff is [261120-phase2-tasks-2.1-2.2-handoff.md](261120-phase2-tasks-2.1-2.2-handoff.md). Journal: `JOURNAL/2026-11-20/160726Z-decision-d76eae.md` (R7a).

## Done

- **`3abd19f59`, ruling R7a.** The coordinator's application of the owner's "scratch repo ... no value". Proof `P7` covers a STANDALONE repository.
  - `RepoFindings.standalone_roots` holds the work tree, plus the git directory when that lies outside the work tree.
  - `other_roots` holds every other repository root. A path is P7 when the deepest root holding it is standalone.
  - Files beside the repository are judged on their own.
  - DESIGN section 0 (R7a paragraph), the R7 row, 3.2 (P7 row), 3.3, 3.6 and 13, PLAN Goals, Task 2.1 and Success Criteria, both module docstrings and release note 017 are updated.
- **`8ec2ce912`, Task 2.3.**
  - `scratch_repos.blob_id` computes git's `hash-object --no-filters` id in process. It opens `O_NOFOLLOW|O_NONBLOCK`, checks with `fstat` that the file is regular, and reads exactly the stat size. A test pins it against real git: empty, CRLF, binary and sha256 files.
  - `scratch_sweep._with_p3` re-judges an UNCERTAIN entry when every uncovered node is a regular file, against `ProjectGit.remote_blobs`.
  - `HashBudget` (`P3_MAX_FILES`, `P3_MAX_BYTES`) bounds the hashing per sweep. When it runs out, the remaining files stay UNCERTAIN and the report adds `P3_BUDGET_NOTE`.
  - The related-clone dirty-file check now uses `blob_id` too, so the review item about `hash-object` following a link is closed.
  - Tests cover a blob only on an unpushed branch, a blob in history but not on the default tip, and a link beside a copy.
- **`035744cbe`, review items.**
  - A mutation control test: the same stat-dirty clone with `GIT_OPTIONAL_LOCKS=1` does get its index rewritten. This shows the guarded test can fail.
  - The `--apply` re-check requirement is written into DESIGN 5.2 step 1 and Task 3.8.
  - The reflog/`ORIG_HEAD` gap is an open DESIGN section 13 row, which Task 3.9 must rule on. It is NOT in the niggles ledger.

Targeted QA: 189+ tests pass across `test_scratch_verdict`, `test_scratch_repos`, `test_scratch_sweep` and `test_cli_scratch_sweep`. ruff, black and `mypy --strict` are clean on the touched source files. Use the venv `/workspace/untracked/venv-workspace-py313-0d6d49c6/bin`, with `PYTHONPATH=src`.

## Remaining

- **Task 2.4: references and REFERENCED.** Advisor guidance, not yet built:
  - Build the reference set once per sweep in the project: `git grep -o -n -E '<escaped root-rel>/[A-Za-z0-9._/-]+'` over HEAD and every local branch not merged into the default branch. If the default branch cannot be resolved, treat every local branch as unmerged.
  - Do not use `-h`, because the report needs the file and line. Check the real output format with several revs and `-z` before writing the parser, and decide what a binary-file line does.
  - Exit 1 means no match. Any other failure is unknown: every due entry is STUCK and the report incomplete, like `TRACKED_UNKNOWN`.
  - Strip a trailing `.` or `/` from each match, and match by path segment (`foo` must not match `foobar`).
  - The verdict order is REFERENCED after PROTECTED and before DISPOSABLE, so it beats P7. Add a test for that.
  - Add REFERENCED to `Verdict` and `_TABLE_ORDER` (`.index()` raises on a missing verdict), and remove it from `NOT_EVALUATED` and its test. Update the CLI help and note 017.
- **Task 2.5: the filing-proposal table** (DESIGN section 6).
  - DESIGN says print the move command, but the sweep docstring says no removal command is printed. Resolve that, or record the deviation in DESIGN.
  - Never print a delete. Quote names, and print no command for a name that is unprintable or starts with `-`.
  - The plan lookup must include `Completed/`.
  - Confirm that `scratch.filing.max_bytes` exists in the config model.

## Deletion surfaces for the security review (new in this unit)

1. **P7.** A `git init` anywhere in scratch turns its work tree, and its git directory, into short-hold DISPOSABLE content. The bound is the deepest-root rule, and classification must succeed for every marker: a BROKEN or PROTECTED marker still decides the entry.
2. **P3.** In-process hashing. `O_NOFOLLOW` guards only the last path component; a parent directory swapped for a link is not caught. That is a dry-run-only proof, and `--apply` must re-classify through directory descriptors.
3. **Open reflog gap** (DESIGN section 13).
