# Handoff: security-review fixes (D-EXEC, F-BYPS) for the dry-run sweep

Branch `agent-acff915e4bf3b86e6-0a26f829`, head `8b7095442` (pushed). origin/main was merged
(already up to date). Reviews: `/workspace/untracked/agent-reports/auto/261120-164356-security-reviewer-a3e346bb755b24722.md`
(D-EXEC) and `.../261120-164713-security-reviewer-a56e8977d29ec301e.md` (F-BYPS). Read both.

## Done (commit 8b7095442, `core/scratch_repos.py` + `tests/unit/core/test_scratch_repos.py`)

- D-EXEC 2: `read_small_regular_file(path, limit)` (public, in scratch_repos): lstat + regular
  check + `O_NOFOLLOW|O_NONBLOCK` + fstat + size cap. `_read_pointer` uses it for the `.git` file
  and `commondir`. `_target`'s OUTSIDE_POINTING reason no longer echoes the pointer. Tests:
  `TestPointerFiles` (FIFO commondir, symlinked commondir with secret text, FIFO `.git`, no echo).
- D-EXEC 1: `NESTED_GIT_FLAGS` gained `submodule.recurse=false`, `diff.ignoreSubmodules=all`;
  status uses `--ignore-submodules=all`; `_dirty_problems` first runs `ls-files --stage -z` and
  any mode-160000 entry makes the related clone PROTECTED ("gitlink(s) whose state is not
  proved"). Tests: inner-repo filter sentinel (same-size edit so git must hash: a size change
  never runs the filter, which is why a first version of the test passed at RED) and a pushed
  clone whose index holds a gitlink.
- D-EXEC 3: `shlex.quote` in the registered-worktree advice; test with `wt x;y`.
- D-EXEC note: `branch` allowlist adds the lowercased `branch_records` keys (CREATOR, CREATED,
  ROUTE, TOUCHED); parametrised test that a pushed clone carrying each still gets P4.

## Left, with the design already decided (advisor-reviewed)

1. **F-BYPS 1 + classifier half of F-BYPS 2** (`scratch_repos.py`). In `_classify_one`, before
   the STANDALONE return and for RELATED too: for each admin dir `<common>/worktrees/<id>` (find
   via walk nodes: `<common_rel>/worktrees/<id>/HEAD`), read `gitdir` with
   `read_small_regular_file`; unreadable -> BROKEN; target outside the entry -> PROTECTED
   (reason names `<id>` and the marker, never pointer content); target inside but no such marker
   in the walk (worktree dir deleted) -> PROTECTED. For RELATED, add each admin HEAD to the tip
   set: run `rev-parse --verify --quiet HEAD^{commit}` with `--git-dir=<admin dir>` (no
   work tree). Tests: outside `git worktree add --detach` + unpushed commit on a clone (P4 today);
   standalone `sa` with linked worktree in another dir (P7 today); in-entry detached worktree
   with unpushed commit whose directory was then removed (proves the tip-set half).
2. **F-BYPS 2 cross-entry** (`scratch_sweep.py`). `_judge_entry` also returns, for every entry
   whatever its verdict, the targets of its `.git` FILE markers (walk markers; read with
   `read_small_regular_file`, lexical and realpath forms). Post-pass in `run_sweep`: an entry
   another entry points into, with verdict DISPOSABLE/UNCERTAIN/REFERENCED -> PROTECTED, reason
   names the pointing marker path; clear its `filing_destination`/`filing_command` (propose ran
   on the old verdict). An unreadable pointer or an unfinished walk elsewhere = unknown:
   DISPOSABLE rows -> STUCK and an incomplete reason. Test: `git init --separate-git-dir` or a
   linked worktree whose admin repo is in another entry.
3. **F-BYPS 4** (`scratch_verdict.py`). P2-by-venv requires `pyvenv.cfg` (regular) AND a
   `bin/python*` or `Scripts/` node AND a `lib*/` directory; it covers ONLY `pyvenv.cfg` and
   paths under `bin/ Scripts/ lib*/ Lib/ include/ Include/ share/` of the venv dir, never
   siblings. Update the fixture at test_scratch_verdict.py ~375 (it has `lib/site.py` with no
   `lib` node; detect `lib*` by path prefix). Tests: lone `pyvenv.cfg` + findings.md/harness.py
   -> UNCERTAIN; full shape + sibling findings.md -> UNCERTAIN. Check what a real
   `python -m venv` writes at top level (a `.gitignore`? decide explicitly).
4. **F-BYPS 3** (`scratch_references.py`). Only for roots deeper than `untracked/<name>`:
   search the shortest qualifying ancestor's pattern (`untracked/<name>/[class]+`), and a match
   whose stripped form equals the root or any ancestor under `untracked/` (brief, taken
   literally, includes `untracked/scratch`) applies to EVERY entry (add a whole-root sites
   field used by `for_entry`). Matches outside the root that are not ancestors are ignored,
   not `_Unknown`. Default-root pattern untouched; test that a bare `untracked/scratch/` mention
   leaves default-root entries alone. Consequence to report: in this repo every sub-root sweep
   becomes REFERENCED (docs mention `untracked/scratch/` everywhere); coordinator to rule.
5. **Low**: empty `inputs.cwds` -> incomplete reason, and due non-LIVE entries STUCK
   ("liveness unknown"): add a `liveness_unknown` param to `judge` checked right after the TTL
   rung. Update `test_an_empty_cwd_map_is_noted`. Residual: partially unreadable pids are still
   silently skipped by `default_process_cwds`.
6. DESIGN sections 3.2, 3.3, 3.4, 13 updated; one `mkplan.bash --journal` per unit (including
   the done D-EXEC unit, not yet journalled).
7. Final: re-run the reviewers' probes under `timeout` with `PYTHONPATH=<worktree>/src`
   (`/workspace/untracked/scratch/fbyps-00627/bin/probe.py`, `d-exec-probe-627*`). Do not sweep
   the real `/workspace/untracked/scratch` before then.

## Running tests

`PYTHONPATH=$PWD/src timeout 500 /workspace/.venv/bin/python -m pytest -q -p no:cacheprovider <files> -o addopts=""` (no xdist, no pytest-timeout; write output to a file, do not pipe to
tail). Repo tests ~10s; sweep tests ~100s.
