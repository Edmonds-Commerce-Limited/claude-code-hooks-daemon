VERDICT: FAIL

# Release 3.75.0, Step 10 code review gate, re-run (git diff v3.74.0..release/3.75.0 -- src/)

Last tag confirmed: `v3.74.0` (`git describe --tags --abbrev=0`). Branch `release/3.75.0` at `5ba2d30df`. 92 files under `src/` (+9663/-1534). Read-only: nothing was edited, committed or pushed. Probe scripts and outputs: `untracked/scratch/s10r/`.

Since the first run (`70c48bf55`), 35 `src/` files changed (+1935/-463): the Plan 00618 fixes, D-1/D-2, and Plan 00617 (`3fc5060e5`, the park-commit classifier; not covered by the first run).

## Why FAIL

Every fix from the first run holds, and no change since that run loosens a guard beyond the owner-approved D-1/D-2. The FAIL rests on one pre-existing defect, S-1. It is an in-scope fail-open in the secret guard ("a global option" respelling: `ARCHITECTURE.md` threat model, line 796; `git -C sub ...` is listed as in scope at line 820). It was not introduced by this release: v3.74.0 gives the same verdict. Under RELEASING.md's "A release carries no known defect", the release needs a fix or the owner's explicit acceptance of a deferral. If the owner accepts S-1 as deferred (filed as a plan), this gate is otherwise a PASS.

## Findings

### S-1 (IMPORTANT, defect, pre-existing; FAIL driver): `git -C <dir> grep --no-index` reads a protected file unjudged

- **Location.** `src/claude_code_hooks_daemon/utils/recursive_search.py:461-462` (`_search_reads`: `if relocated: return`). `search_command` (:150-172) marks any `-C`/`--git-dir`/`--work-tree` git grep as relocated, and the caller then yields no read at all, so nothing is judged. `secret_file_matching.effective_cwds` (:3420) follows `cd`/`pushd` only, never `git -C`.
- **Failing input.** In the probe project the root holds `<P>` and `deep/` holds `key.<protected-ext>`. Through `SecretFileGuardHandler.matches/handle`:
  - `git -C deep grep --no-index -e .` is ALLOW.
  - `git --no-pager -C deep grep --no-index -e .` and `git -C deep grep --no-index -e . .` are ALLOW.
  - The controls are DENY: `cd deep && git grep --no-index -e .` and `git grep --no-index -e . deep`.
- **That git really reads it.** In a scratch repo with `deep/key.dat` gitignored, `git -C deep grep --no-index -e TOKEN` printed `key.dat:TOKENVALUE`. So an ignored file's content reaches output (`--untracked` is the same class).
- **Regression check.** Same verdicts against a `git archive v3.74.0` export (`probe_secret_old.py`; the import path was checked to resolve to the old tree). So this is pre-existing, not a regression.
- **Remediation.** Place the relocated root rather than skipping it. Resolve a literal `-C <dir>` (cumulatively, relative to the hook cwd) as the search cwd. For `--git-dir`/`--work-tree`, or a `-C` value that cannot be placed, fail closed: judge the hook cwd's whole tree, or treat it as unjudgeable. Add deny tests for the three ALLOW shapes above, plus the `cd` equivalence. The same `relocated` skip likely affects `flaggable_content_channel_guard` (its advisory names "a `git -C`" as unplaceable). Check it in the same plan.
- **Evidence.** `untracked/scratch/s10r/probe_secret.py`, `cases5.txt`, `probe_secret_old.py`.

### S-2 (SUGGESTION, doc drift, guard text): the remote-delete and delete-branch deny texts still describe the blob-only proof

- **Location.** `src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py:404` (`_PUSH_DELETE_VERBOSE`: "every file version on it is byte-identical to one the default branch holds"). Also `:1493` ("every file version byte-identical to a blob still reachable from `main`").
- **Problem.** Since B-1, the content tier also requires the per-path net change (`branch_safety._net_change_held` → `remote_branch_proof.holds_net_change`). The text promises a weaker proof than the one enforced. It loosens nothing, but it misleads an agent about why a delete is refused. The B-1 fix report flagged this and left it unfixed.
- **Remediation.** Reword both strings to "every file version survives AND a commit on the default's first-parent history holds the branch's net change". Update the matching rule text and doc rows, then run the destructive_git handler tests.

### S-3 (NIT, carried from the D-1/D-2 review, not re-verified): the dormancy `warn` advisory at stop is unreachable today

- **Location.** `src/claude_code_hooks_daemon/core/branch_stop_guard.py`, `_pressure_findings` (the `advisory=dormancy == "warn"` branch).
- **Problem.** The journal (`JOURNAL/2026-11-17/111756Z-decision-7bb443.md`) records that the inventory reports dormancy only at the block stage. If so, the warn branch never fires in practice.
- **Remediation.** Either confirm with a test that drives `dormancy.mode: warn` to a real BLOCK-stage record through `judge_stop`, or document the limit.

## Verified fixes from the first run

| Item | Verdict | How checked |
| ---- | ------- | ----------- |
| B-1 delete-branch content proof | HOLDS | Reviewer repro rebuilt in `probe_delete.py`: tier `unproven`, refused. `classify_branch` requires blob identity AND `holds_net_change` (`branch_safety.py:841-861`). |
| B-2 stop-guard hand-over | HOLDS (diff-read + tests) | `branch_stop_gate._hand_over`: a branch in `own` is handed over only on a queue record or git lock (`harness_directory=False`). Newly judged refusals use their own capped counter, so it can only narrow pre-B-2 behaviour. |
| B-3/B-4 git search-option scope | HOLDS | `git grep -G {p}`, `git blame -S {p} f` → DENY. The exemption is scoped by `_GIT_SEARCH_VALUE_SUBCOMMANDS` (`secret_file_matching.py:2117-2131`). The separate-spelling previous-word check fails closed. |
| B-5 grep first searched directory | HOLDS | `-ezz`, `--regexp=zz`, the abbreviations `--rege=`/`--reg=`/`--fil=`, `rg -ezz`/`--regexp=`/`-f` → DENY. `pattern_supplied` returns not-clean (`:2291`). |
| D-1 warn mode / D-2 same-tip count | HOLD (owner-approved loosenings) | `_pressure_findings` sets `advisory` from each pool mode and counts with `open_work_count` (tip-deduplicated `pool_count`). |
| Owner decisions D-3 (no) / D-4 (A) | Accepted | Journal `111756Z-decision-7bb443.md`. The D-4 limit is stated in release note 092 and ledger 00474. |

Targeted tests: `test_branch_stop_gate.py`, `test_branch_stop_gate_pool_modes.py`, `test_secret_file_guard_option_values.py`, `test_branch_safety.py`, `test_park_commit_classifier.py`: 480 passed (`untracked/scratch/s10r/pytest1.txt`).

## Loosening hunt

- **Secret guard, differential.** 4 case sets (about 150 commands: git search options, grep/rg option grammar, directory readers, `xargs`/`find -exec`) were run against v3.74.0 and the release tip. Every DENY→ALLOW flip is an intended exemption whose value git or grep does not open as a file: `git log/show/diff/diff-tree/diff-index/format-patch/rev-list/whatchanged` `-S`/`-G`/`--grep`/`--author`/`--committer` values; `grep -A NUM`, `-d/-D ACTION`, `--context NUM`, `rg -E ENCODING`; `grep -rzz deep sub` (pattern `deep`, path `sub`). Every other change is ALLOW→DENY (tar, cp -r, zip, rsync, diff -r, `git diff --no-index`, `find -exec`, `xargs cat`). Outputs: `old{1..4}.out` / `new{1..4}.out`.
- **Delete guard (Plan 00617 park-carried tier, new since the first run).** `probe_delete.py` results:
  - park over merged work → `park-carried`;
  - a forged park message on a commit that changes a file → `unproven`;
  - work then park → `unproven`;
  - merge then park → `unproven`;
  - park message plus extra text → `unproven`;
  - add-then-remove then park → `unproven` (conservative).
  
  `is_park_residue` needs every commit beyond the default to carry the exact writer message, one parent and the parent's tree. That is sound. `patch_equivalent` drops only verified empty park commits from the unique set.
- **Creation guard.** `_carried_refnames` now also excludes unparked-trailer tips that are pure park residue (Plan 00617 design: no work held). Not a loosening of real work.
- **branch_cleanup (N-2, N-3, N-4 deltas).** Code-diff read. Worktree blockers are re-checked immediately before removal. Park records are cleared only for `deleted` names, from a pre-delete snapshot. Hook paths use `prove=False` wording only. No fail-open found.
- **Checklist.** One new priority (`LONG_RUNNING_COMMAND_GUARD = 40`, in the workflow band). No added TODO/FIXME/HACK/breakpoint/debug print in the diff.

## Out of scope (threat model), recorded not counted

- `cat $(find deep -type f)` is ALLOW in both v3.74.0 and the tip. The path is computed by a command substitution, which `effective_cwds` and the mention scanner treat as out of scope by design. `find ... | xargs cat` and `find -exec cat` are DENY.

## Coverage limits

- **Not proven by these probes.** The probe project is not a git repository, so the plain (tracked-view) `git grep` and `git -C deep log -p` ALLOW verdicts prove nothing either way.
- **Not re-read line by line this run** (they rely on the first run's review and the per-group loosening reviews): `grep_option_grammar.py` (exercised by probes only), `recursive_search.py` beyond the git-grep path, `long_running_command.py` and its guard (ships disabled), `relay_repair.py`, `cli.py`, `worktree_create_handler.py` (T-4 rmtree delta), `version_check.py`, `venv_lock.py`, `paths.py`, `scan_scope.py`, `plan_numbering.py`/`git_repo.py` (N-10).
- **N/T fixes from Phase 2.** Not re-run here beyond the five files above. Their red tests are named in `261117-phase2-defects.md`.
- **B-2 live behaviour.** Covered by the test suite only; not re-probed in a scratch repo this run.
