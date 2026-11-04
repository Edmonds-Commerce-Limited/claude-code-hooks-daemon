# Issue 154: read-only remote plan-number scan (Sonnet sub-agent)

Branch worktree-issue-154-plan-number-remote. Brief verified against the code; it was correct.

## Red output (before the fix)

tests/unit/scripts/test_mkplan_remote_scan.py, 9 failed / 3 passed. The collision itself:

- bash: `assert (clone_b/CLAUDE/Plan/00002-from-b).is_dir()` -> False (clone B took 00001, the number clone A had pushed)
- daemon: `AssertionError: assert '00001' == '00002'` from next_plan_number_for_target
- offline tests failed on the missing notice: `assert 0 == 1 ... count('remote could not be checked')`

(The red run used a stub `remote_highest_plan_number` returning None so the behaviour, not an ImportError, failed.)

## Change

- plan_numbering.py: `remote_highest_plan_number(repo_root, plan_subdir)` (default remote = origin else first; `git fetch --quiet --no-tags <remote>` with Timeout.GIT_FETCH_SESSION; per `refs/remotes/<remote>/*` ref one `git ls-tree --name-only <ref> -- <plan>/ <plan>/Completed/ <plan>/Cancelled/`; None when unchecked). `next_plan_number_for_target(..., include_remote=True)` takes max(counter, disk, remote) and writes one stderr line when unchecked. `record_new_plan_document` passes `include_remote=False` (it validates a number, it does not allocate one, and runs on the hook path).
- mkplan.bash (deployed copy and install template, byte-identical): `remote_highest` / `default_remote`, `REMOTE_FETCH_TIMEOUT_SECONDS=30` (pinned to the daemon constant by a test). The scan runs BEFORE the scaffold lock because a fetch may take its whole budget and lock waiters give up after about 10 s. Lock, counter write, folder layout untouched.
- Never pushes (test asserts the bare remote's refs are unchanged).
- Release note: CLAUDE/UPGRADES/UNRELEASED/release-notes/033-plan-number-remote-scan.md.

## Tests

tests/unit/scripts/test_mkplan_remote_scan.py: 12 pass (two clones for bash and daemon, archived plan, feature-branch plan, no-push, no remote, unreachable remote, reachable prints no notice, outside git, timeout parity). Also green: tests/unit/scripts, test_plan_numbering.py, test_plan_workflow.py (191), and tests/unit/handlers plan_number/markdown_organization/plan_numbering (572).

## Limits

Archive folders deeper than Completed/ or Cancelled/ (e.g. Completed/2025/) are not read on the remote, per the brief; the local disk scan still recurses. Every call of next_plan_number_for_target that allocates now performs a fetch.
